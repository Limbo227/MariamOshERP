from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Document, Party
from apps.core.quantities import line_amount
from apps.core.services import reverse_document
from apps.finance.models import OpenItem
from apps.finance.queries import item_remaining
from apps.inventory.models import GoodsReceipt, Product, ReceiptLine, StorageLocation, Warehouse
from apps.inventory.services import record_receipt
from apps.procurement.models import PurchaseOrder, RailwayStation, Shipment
from apps.procurement.services import (
    declare_wagons,
    delete_shipment,
    post_shipment,
    record_shipment,
    unpost_shipment,
    update_shipment,
)
from apps.ui.fields import LooseDecimalField, StyledForm, date_field, qty_field
from apps.ui.formatting import format_money, format_qty, unit_label
from apps.ui.http import (
    cancel_request,
    erp_page,
    error_text,
    pager,
    show_cancelled,
    without_cancelled,
)


class ShipmentForm(StyledForm):
    order = forms.ModelChoiceField(label="Спецификация", queryset=PurchaseOrder.objects.none())
    departure_station = forms.ModelChoiceField(label="Станция отправления", queryset=RailwayStation.objects.none())
    destination_station = forms.ModelChoiceField(
        label="Станция назначения", queryset=RailwayStation.objects.none(), required=False
    )
    quantity = qty_field("Вес нетто, кг")
    wagon_count = forms.IntegerField(label="Число вагонов", min_value=1, initial=1)
    departure_date = date_field("Дата отправления", required=False)
    wagon_number = forms.CharField(label="Номер вагона", required=False)
    arrival_date = date_field("Дата приёмки", required=False)
    notes = forms.CharField(label="Заметка", required=False, widget=forms.Textarea)

    def __init__(self, *args, fixed_order=None, current=None, **kwargs):
        super().__init__(*args, **kwargs)
        orders = PurchaseOrder.objects.select_related("document", "supplier", "contract").order_by(
            "-document__effective_date", "-pk"
        )
        # Shipments carry wheat by contract specification; open specifications only, plus the current one.
        open_specs = Q(contract__isnull=False, operational_status=PurchaseOrder.OperationalStatus.IN_PROGRESS)
        orders = orders.filter(open_specs | Q(pk=current.pk)) if current is not None else orders.filter(open_specs)
        if fixed_order is not None:
            orders = PurchaseOrder.objects.select_related("document", "supplier", "contract")
            orders = orders.filter(pk=fixed_order.pk)
            self.fields["order"].initial = fixed_order.pk
        self.fields["order"].queryset = orders
        self.fields["order"].label_from_instance = _order_label
        stations = RailwayStation.objects.filter(active=True).order_by("name")
        self.fields["departure_station"].queryset = stations
        self.fields["destination_station"].queryset = stations
        self.fields["destination_station"].help_text = "Обычно Манас или Ош. Подставляется последняя использованная."
        if not self.initial.get("destination_station"):
            self.fields["destination_station"].initial = _usual_destination()
        self.fields["wagon_number"].help_text = (
            "Если вагон один. Для нескольких вагонов номера и вес каждого вводятся в карточке поставки."
        )


class ShipmentStatusForm(StyledForm):
    arrival_date = date_field("Дата приёмки", required=False)
    notes = forms.CharField(label="Заметка", required=False, widget=forms.Textarea)

    def __init__(self, *args, shipment, **kwargs):
        super().__init__(*args, **kwargs)
        if shipment.arrival_date:
            self.fields["arrival_date"].initial = shipment.arrival_date
        self.fields["notes"].initial = shipment.notes


class ReceiptForm(StyledForm):
    purchase_line = forms.ModelChoiceField(label="Строка закупки", queryset=PurchaseOrder.objects.none())
    warehouse = forms.ModelChoiceField(label="Склад", queryset=Warehouse.objects.none())
    location = forms.ModelChoiceField(
        label="Место хранения", queryset=StorageLocation.objects.none(), required=False
    )
    quantity = qty_field("Фактически принято")
    bags = forms.IntegerField(label="Мешки", required=False, min_value=1)
    effective_date = date_field("Дата приёмки")
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, order, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        lines = list(order.lines.select_related("product"))
        self.fields["purchase_line"].queryset = order.lines.select_related("product")
        self.fields["purchase_line"].label = "Товар"
        self.fields["purchase_line"].label_from_instance = (
            lambda line: f"{line.product.name}, заказано {format_qty(line.quantity)} {unit_label(line.product.unit)}"
        )
        warehouses = Warehouse.objects.filter(active=True)
        if len(lines) == 1:
            self.fields["purchase_line"].initial = lines[0].pk
            category = lines[0].product.category_id
            warehouses = warehouses.filter(Q(category__isnull=True) | Q(category_id=category))
            self.fields["quantity"].label = f"Фактически принято, {unit_label(lines[0].product.unit)}"
        self.fields["warehouse"].queryset = warehouses.order_by("name")
        if warehouses.count() == 1:
            self.fields["warehouse"].initial = warehouses.first().pk
        self.fields["location"].queryset = StorageLocation.objects.filter(active=True, warehouse__active=True).select_related(
            "warehouse"
        )
        self.fields["location"].widget = forms.HiddenInput()
        self.fields["bags"].widget = forms.HiddenInput()
        self.fields["effective_date"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        line = cleaned.get("purchase_line")
        warehouse = cleaned.get("warehouse")
        location = cleaned.get("location")
        quantity = cleaned.get("quantity")
        if line and line.order_id != self.order.pk:
            self.add_error("purchase_line", "Строка не относится к выбранной закупке.")
        if location and warehouse and location.warehouse_id != warehouse.id:
            self.add_error("location", "Место хранения не относится к выбранному складу.")
        cleaned["bags"] = None
        if line and quantity is not None:
            product = line.product
            if product.unit == Product.Unit.KG and product.package_kg:
                bags = quantity / product.package_kg
                if bags != bags.to_integral_value():
                    self.add_error("quantity", f"Вес должен делиться на мешки по {format_qty(product.package_kg)} кг.")
                else:
                    cleaned["bags"] = int(bags)
        return cleaned


def _usual_destination():
    """Last destination used, otherwise a station called Манас."""
    last = (
        Shipment.objects.filter(destination_station__active=True)
        .order_by("-pk")
        .values_list("destination_station_id", flat=True)
        .first()
    )
    if last:
        return last
    manas = RailwayStation.objects.filter(active=True, name__icontains="манас").values_list("pk", flat=True).first()
    return manas


def _order_label(order):
    spec = ""
    if order.contract_id:
        spec = f", {order.contract.number} / {order.specification_number}"
    return f"{order.document.number} — {order.supplier.name}{spec}"


def _shipment_qs():
    return Shipment.objects.select_related(
        "order__document", "order__supplier", "order__contract", "departure_station", "destination_station"
    ).prefetch_related("wagons", "order__lines__product").order_by("-departure_date", "-pk")


@erp_page
def shipment_list(request):
    from apps.ui.http import remember_list

    remember_list(request, "shipments")
    qs = _shipment_qs()
    q = request.GET.get("q", "").strip()
    supplier = request.GET.get("supplier", "")
    contract = request.GET.get("contract", "")
    status = request.GET.get("status", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if q:
        qs = qs.filter(
            Q(wagons__wagon_number__icontains=q)
            | Q(order__supplier__name__icontains=q)
            | Q(order__specification_number__icontains=q)
            | Q(order__contract__number__icontains=q)
            | Q(order__document__number__icontains=q)
        )
    if supplier:
        qs = qs.filter(order__supplier_id=supplier)
    if contract:
        qs = qs.filter(order__contract_id=contract)
    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(departure_date__gte=date_from)
    if date_to:
        qs = qs.filter(departure_date__lte=date_to)
    qs = qs.distinct()
    page, query = pager(request, qs)
    rows = list(page.object_list)
    for shipment in rows:
        lines = list(shipment.order.lines.all())
        shipment.ui_line = lines[0] if lines else None
    page.object_list = rows
    from apps.procurement.models import PurchaseContract

    return render(
        request,
        "ui/shipment_list.html",
        {
            "page": page,
            "query": query,
            "q": q,
            "supplier": supplier,
            "contract": contract,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "suppliers": Party.objects.filter(is_supplier=True).order_by("name"),
            "contracts": PurchaseContract.objects.select_related("supplier").order_by("number"),
            "statuses": Shipment.Status.choices,
        },
    )


@erp_page
def shipment_create(request):
    order_id = request.GET.get("order")
    order = PurchaseOrder.objects.filter(pk=order_id).select_related("document", "supplier").first() if order_id else None
    if request.method == "POST":
        form = ShipmentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                shipment = record_shipment(
                    order=data["order"],
                    quantity=data["quantity"],
                    departure_date=data.get("departure_date"),
                    wagon_number=data.get("wagon_number") or "",
                    arrival_date=data.get("arrival_date"),
                    notes=data.get("notes") or "",
                    departure_station=data["departure_station"],
                    destination_station=data.get("destination_station"),
                    wagon_count=data["wagon_count"],
                    actor=request.user,
                )
            except ValidationError as exc:
                form.add_error(None, error_text(exc))
            else:
                messages.success(request, "Черновик поставки сохранён. Склад и долг изменятся после проведения.")
                return redirect("shipment_detail", shipment.pk)
    else:
        initial = {"order": order.pk} if order else None
        form = ShipmentForm(initial=initial, fixed_order=order)
    return render(request, "ui/shipment_form.html", {"form": form, "order": order})


@erp_page
def shipment_edit(request, pk):
    shipment = get_object_or_404(_shipment_qs(), pk=pk)
    initial = {
        "order": shipment.order_id,
        "departure_station": shipment.departure_station_id,
        "destination_station": shipment.destination_station_id,
        "quantity": shipment.quantity,
        "wagon_count": shipment.wagon_count,
        "departure_date": shipment.departure_date,
        "wagon_number": shipment.wagon_number,
        "arrival_date": shipment.arrival_date,
        "notes": shipment.notes,
    }
    form = ShipmentForm(request.POST or None, initial=initial, current=shipment.order)
    form.fields["wagon_number"].disabled = True
    form.fields["wagon_number"].help_text = "Номера вагонов меняются в карточке поставки."
    if shipment.status == Shipment.Status.POSTED:
        for name in ("order", "quantity", "wagon_count", "arrival_date"):
            form.fields[name].disabled = True
        form.fields["order"].help_text = (
            "Поставка проведена: спецификация, вес, число вагонов и дата приёмки заблокированы. "
            "Чтобы их изменить, нажмите в карточке «Отменить выполнение»."
        )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            update_shipment(
                shipment,
                order=data["order"],
                quantity=data["quantity"],
                wagon_count=data["wagon_count"],
                departure_date=data.get("departure_date"),
                arrival_date=data.get("arrival_date"),
                notes=data.get("notes") or "",
                departure_station=data["departure_station"],
                destination_station=data.get("destination_station"),
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Поставка сохранена.")
            return redirect("shipment_detail", shipment.pk)
    return render(request, "ui/shipment_form.html", {"form": form, "order": shipment.order, "editing": shipment})


@erp_page
@require_POST
def shipment_delete(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    try:
        delete_shipment(shipment, actor=request.user)
    except ValidationError as exc:
        messages.error(request, error_text(exc))
        return redirect("shipment_detail", shipment.pk)
    messages.success(request, "Черновик поставки удалён.")
    return redirect("shipment_list")


@erp_page
def shipment_detail(request, pk):
    shipment = get_object_or_404(_shipment_qs(), pk=pk)
    return _shipment_page(request, shipment)


def _shipment_page(request, shipment, *, wagon_rows=None, wagon_error=""):
    order = shipment.order
    accepted = (
        ReceiptLine.objects.filter(purchase_line__order=order, receipt__document__reversal__isnull=True).aggregate(
            total=Sum("quantity")
        )["total"]
        or Decimal("0")
    )
    receipts = (
        GoodsReceipt.objects.filter(lines__purchase_line__order=order)
        .select_related("document", "warehouse")
        .distinct()
    )
    expenses = shipment.expenses.select_related("document", "account", "operation")
    status_form = ShipmentStatusForm(shipment=shipment)
    lines = list(order.lines.all())
    line = lines[0] if lines else None
    if wagon_rows is None:
        wagon_rows = [{"wagon_number": w.wagon_number, "weight_kg": format_qty(w.weight_kg)} for w in shipment.wagons.all()]
    blank = max(shipment.wagon_count - len(wagon_rows), 1 if wagon_rows else 2)
    return render(
        request,
        "ui/shipment_detail.html",
        {
            "shipment": shipment,
            "accepted": accepted,
            "receipts": receipts,
            "expenses": expenses,
            "status_form": status_form,
            "line": line,
            "wagons": wagon_rows,
            "wagon_error": wagon_error,
            "blank_rows": range(blank),
        },
        status=400 if wagon_error else 200,
    )


@erp_page
@require_POST
def shipment_wagons(request, pk):
    shipment = get_object_or_404(_shipment_qs(), pk=pk)
    numbers = request.POST.getlist("wagon_number")
    weights = request.POST.getlist("weight_kg")
    typed = [
        {"wagon_number": number, "weight_kg": weight}
        for number, weight in zip(numbers, weights)
        if (number or "").strip() or str(weight or "").strip()
    ]
    wagons = []
    weight_field = LooseDecimalField(max_digits=18, decimal_places=3, min_value=Decimal("0.001"))
    try:
        for number, weight in zip(numbers, weights):
            if not (number or "").strip() and not str(weight or "").strip():
                continue
            wagons.append({"wagon_number": number, "weight_kg": weight_field.clean(weight)})
        if not wagons:
            raise ValidationError("Укажите номер вагона и вес.")
        declare_wagons(
            shipment,
            wagons,
            complete=request.POST.get("complete") == "1",
            actor=request.user,
        )
    except (ValidationError, forms.ValidationError) as exc:
        return _shipment_page(request, shipment, wagon_rows=typed, wagon_error=error_text(exc))
    else:
        if shipment.status == Shipment.Status.POSTED:
            messages.success(request, "Вагоны сохранены. Проведённый вес и долг не изменились.")
        else:
            messages.success(request, "Вагоны сохранены.")
    return redirect("shipment_detail", shipment.pk)


@erp_page
@require_POST
def shipment_status(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    action = request.POST.get("action") or ""
    try:
        if action == "unpost":
            unpost_shipment(shipment, actor=request.user)
            messages.success(request, "Выполнение отменено. Поставка снова черновик.")
        elif action == "post":
            if request.POST.get("arrival_date"):
                from apps.procurement.services import update_shipment

                update_shipment(
                    shipment,
                    arrival_date=request.POST.get("arrival_date"),
                    notes=request.POST.get("notes"),
                    actor=request.user,
                )
            post_shipment(shipment, actor=request.user)
            messages.success(request, "Поставка проведена: товар на складе, долг поставщику создан.")
        else:
            messages.error(request, "Укажите проведение или отмену выполнения.")
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    return redirect("shipment_detail", shipment.pk)


def _posted_orders():
    return PurchaseOrder.objects.select_related("document", "supplier", "contract").order_by(
        "-document__effective_date", "-pk"
    )


def line_context(line):
    order = line.order
    accepted = (
        ReceiptLine.objects.filter(
            purchase_line=line,
            receipt__document__state=Document.State.POSTED,
            receipt__document__reversal__isnull=True,
        ).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )
    dispatched = (
        Shipment.objects.filter(order=order, status=Shipment.Status.POSTED).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )
    return {
        "ordered": line.quantity,
        "dispatched": dispatched,
        "accepted": accepted,
        "unit": line.product.get_unit_display(),
        "price": line.price,
        "currency": order.currency,
        "product": line.product,
    }


def _preview_text(line, quantity):
    amount = line_amount(quantity, line.price)
    return (
        f"Принято {format_qty(quantity)} {line.product.get_unit_display()}. "
        f"Цена {format_money(line.price)} {line.order.currency}. "
        f"Расчётный долг поставщику: {format_money(amount)} {line.order.currency}. "
        "Окончательную сумму записывает проведение."
    )


@erp_page
def receipt_list(request):
    qs = GoodsReceipt.objects.select_related("document", "supplier", "warehouse").order_by(
        "-document__effective_date", "-pk"
    )
    q = request.GET.get("q", "").strip()
    supplier = request.GET.get("supplier", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if q:
        qs = qs.filter(Q(document__number__icontains=q) | Q(supplier__name__icontains=q))
    if supplier:
        qs = qs.filter(supplier_id=supplier)
    if date_from:
        qs = qs.filter(document__effective_date__gte=date_from)
    if date_to:
        qs = qs.filter(document__effective_date__lte=date_to)
    cancelled = show_cancelled(request)
    if not cancelled:
        qs = without_cancelled(qs)
    page, query = pager(request, qs)
    rows = list(page.object_list)
    cancelled_ids = set(
        GoodsReceipt.objects.filter(pk__in=[row.pk for row in rows], document__reversal__isnull=False).values_list(
            "pk", flat=True
        )
    )
    shipment_of = dict(
        Shipment.objects.filter(receipt_id__in=[row.pk for row in rows]).values_list("receipt_id", "pk")
    )
    for row in rows:
        row.is_cancelled = row.pk in cancelled_ids
        row.shipment_id = shipment_of.get(row.pk)
    totals = {
        row["receipt_id"]: row["total"]
        for row in ReceiptLine.objects.filter(receipt_id__in=[item.pk for item in rows])
        .values("receipt_id")
        .annotate(total=Sum("quantity"))
    }
    for row in rows:
        row.accepted_qty = totals.get(row.pk) or Decimal("0")
    page.object_list = rows
    return render(
        request,
        "ui/receipt_list.html",
        {
            "page": page,
            "query": query,
            "q": q,
            "supplier": supplier,
            "date_from": date_from,
            "date_to": date_to,
            "cancelled": cancelled,
            "suppliers": Party.objects.filter(is_supplier=True).order_by("name"),
        },
    )


@erp_page
def receipt_create(request):
    supplier_id = request.GET.get("supplier") or request.POST.get("supplier")
    order_id = request.GET.get("order") or request.POST.get("order")
    suppliers = Party.objects.filter(is_supplier=True, active=True, purchases__contract__isnull=True).distinct().order_by("name")
    # Wheat by specification is received by posting its shipment, so only ordinary orders are offered here.
    orders = _posted_orders().filter(contract__isnull=True, document__reversal__isnull=True).prefetch_related(
        "lines__product"
    )
    if supplier_id:
        orders = orders.filter(supplier_id=supplier_id)
    orders = list(orders[:200])
    for row in orders:
        row.ui_products = ", ".join(line.product.name for line in row.lines.all())
    order = _posted_orders().filter(pk=order_id).first() if str(order_id or "").isdigit() else None
    form = None
    preview = None
    context = None
    if order is not None:
        form = ReceiptForm(request.POST or None, order=order)
        if request.method == "POST":
            action = request.POST.get("action")
            if form.is_valid() and action == "post":
                data = form.cleaned_data
                line = data["purchase_line"]
                try:
                    receipt = record_receipt(
                        supplier=order.supplier,
                        warehouse=data["warehouse"],
                        effective_date=data["effective_date"],
                        lines=[
                            {
                                "product": line.product,
                                "location": data.get("location"),
                                "quantity": data["quantity"],
                                "bags": data.get("bags"),
                                "purchase_line": line,
                            }
                        ],
                        note=data.get("note") or "",
                        actor=request.user,
                    )
                except ValidationError as exc:
                    form.add_error(None, error_text(exc))
                else:
                    messages.success(
                        request,
                        f"Приёмка {receipt.document.number} проведена. Остаток увеличен, долг поставщику записан.",
                    )
                    return redirect("receipt_detail", receipt.pk)
            if form.is_valid():
                preview = _preview_text(form.cleaned_data["purchase_line"], form.cleaned_data["quantity"])
                context = line_context(form.cleaned_data["purchase_line"])
        elif request.GET.get("line"):
            line = order.lines.filter(pk=request.GET.get("line")).select_related("product", "order").first()
            if line:
                context = line_context(line)
        if context is None:
            line = order.lines.select_related("product", "order").first()
            if line:
                context = line_context(line)
    return render(
        request,
        "ui/receipt_form.html",
        {
            "suppliers": suppliers,
            "orders": orders,
            "supplier_id": str(supplier_id or ""),
            "order": order,
            "form": form,
            "preview": preview,
            "context": context,
        },
    )


@erp_page
def receipt_detail(request, pk):
    receipt = get_object_or_404(
        GoodsReceipt.objects.select_related("document", "supplier", "warehouse"),
        pk=pk,
    )
    lines = []
    payable = Decimal("0")
    currency = ""
    for line in receipt.lines.select_related("product", "location", "purchase_line__order"):
        amount = line_amount(line.quantity, line.purchase_line.price)
        payable += amount
        currency = line.purchase_line.order.currency
        lines.append({"line": line, "amount": amount})
    debts = []
    for item in OpenItem.objects.filter(document=receipt.document):
        debts.append({"item": item, "left": item_remaining(item)})
    try:
        reversal = receipt.document.reversal
    except ObjectDoesNotExist:
        reversal = None
    source_shipment = Shipment.objects.filter(receipt=receipt).first()
    return render(
        request,
        "ui/receipt_detail.html",
        {
            "receipt": receipt,
            "lines": lines,
            "payable": payable,
            "currency": currency,
            "debts": debts,
            "reversal": reversal,
            "source_shipment": source_shipment,
            "today": timezone.localdate(),
        },
    )


@erp_page
@require_POST
def receipt_reverse(request, pk):
    receipt = get_object_or_404(GoodsReceipt.objects.select_related("document"), pk=pk)
    if Shipment.objects.filter(receipt=receipt).exists():
        messages.error(request, "Эта приёмка создана поставкой. Отмените выполнение поставки.")
        return redirect("receipt_detail", receipt.pk)
    effective, note = cancel_request(request)
    if effective is None:
        return redirect("receipt_detail", receipt.pk)
    try:
        reverse_document(receipt.document, effective_date=effective, note=note, actor=request.user)
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    else:
        messages.success(request, "Приёмка отменена. Товар снят со склада, долг по ней закрыт.")
    return redirect("receipt_detail", receipt.pk)
