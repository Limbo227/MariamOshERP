from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Currency, Document, Party
from apps.core.quantities import line_amount
from apps.inventory.checks import ensure_whole
from apps.inventory.models import Product
from apps.procurement.models import DeliveryTerm, PurchaseContract, PurchaseOrder, Shipment
from apps.procurement.services import (
    complete_specification,
    delete_specification,
    record_contract,
    record_purchase,
    reopen_specification,
    update_specification,
)
from apps.ui.fields import (
    LooseDecimalField,
    StyledForm,
    StyledModelForm,
    date_field,
    price_field,
    qty_field,
)
from apps.ui.figures import fill_percent, order_figures, specification_statement
from apps.ui.formatting import format_money, format_qty, unit_label
from apps.ui.http import erp_page, error_text, pager, remember_list, stored_back


class ContractForm(StyledModelForm):
    class Meta:
        model = PurchaseContract
        fields = [
            "supplier",
            "number",
            "contract_date",
            "end_date",
            "currency",
            "delivery_term",
            "volume_tons",
            "amount_limit",
            "prepayment_percent",
            "payment_terms",
            "description",
            "active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Party.objects.filter(is_supplier=True, active=True)
        if self.instance.pk and self.instance.supplier_id:
            suppliers = Party.objects.filter(Q(pk=self.instance.supplier_id) | Q(is_supplier=True, active=True))
        self.fields["supplier"].queryset = suppliers.order_by("name")
        self.fields["supplier"].label = "Поставщик"
        self.fields["contract_date"].label = "Дата договора"
        if not self.instance.pk:
            self.fields["contract_date"].initial = timezone.localdate()
        self.fields["end_date"].help_text = "Пусто — бессрочно."
        self.fields["volume_tons"].help_text = "Справочно: сколько тонн по договору всего."
        self.fields["amount_limit"].help_text = "Справочно, в валюте договора."
        self.fields["prepayment_percent"].help_text = "Например 30 — значит 30 % предоплаты."
        self.fields["payment_terms"].help_text = "Коротко: «30 % предоплата, остаток 10 дней после поставки»."
        self.fields["description"].label = "Заметка"
        self.fields["currency"].required = False
        self.fields["currency"].help_text = "Валюта новых спецификаций. Уже созданные спецификации не пересчитываются."
        terms = DeliveryTerm.objects.filter(active=True)
        if self.instance.pk and self.instance.delivery_term_id:
            terms = DeliveryTerm.objects.filter(Q(pk=self.instance.delivery_term_id) | Q(active=True))
        self.fields["delivery_term"].queryset = terms.order_by("name")
        self.fields["delivery_term"].required = False
        if self.instance.pk and self.instance.specifications.exists():
            self.fields["supplier"].disabled = True
            self.fields["number"].disabled = True
            self.fields["number"].help_text = "У договора со спецификациями нельзя менять поставщика или номер."

    def clean_currency(self):
        return self.cleaned_data.get("currency") or Currency.KGS


class PurchaseForm(StyledForm):
    supplier = forms.ModelChoiceField(label="Поставщик", queryset=Party.objects.none())
    effective_date = date_field("Дата")
    contract = forms.ModelChoiceField(label="Договор", queryset=PurchaseContract.objects.none(), required=False)
    specification_number = forms.CharField(label="Номер спецификации", required=False)
    product = forms.ModelChoiceField(label="Товар", queryset=Product.objects.none())
    quantity = qty_field("Количество")
    price = price_field("Цена")
    currency = forms.ChoiceField(label="Валюта", choices=PurchaseOrder.Currency.choices)
    bags = forms.IntegerField(label="Мешки", required=False, min_value=1)
    tolerance_percent = LooseDecimalField(
        label="Допуск, %",
        required=False,
        min_value=Decimal("0"),
        max_digits=6,
        decimal_places=2,
    )
    delivery_term = forms.ModelChoiceField(label="Условие поставки", queryset=DeliveryTerm.objects.none(), required=False)
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, fixed_contract=None, **kwargs):
        self.fixed_contract = fixed_contract
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Party.objects.filter(is_supplier=True, active=True).order_by("name")
        contracts = PurchaseContract.objects.filter(active=True).select_related("supplier").order_by("-contract_date")
        self.fields["contract"].queryset = contracts
        self.fields["contract"].empty_label = "Без договора — обычный заказ"
        products = Product.objects.filter(active=True).order_by("name")
        self.fields["delivery_term"].queryset = DeliveryTerm.objects.filter(active=True).order_by("name")
        self.fields["tolerance_percent"].help_text = (
            "Справочно, обычно ±10%. Перевес не блокирует поставки — оператор сам отмечает «Выполнено»."
        )
        # Sacks are counted by the product itself (unit «мешок»), so nobody types them twice.
        self.fields["bags"].widget = forms.HiddenInput()
        if fixed_contract is not None:
            self.fields["contract"].initial = fixed_contract.pk
            self.fields["contract"].queryset = PurchaseContract.objects.filter(pk=fixed_contract.pk)
            self.fields["supplier"].initial = fixed_contract.supplier_id
            self.fields["supplier"].queryset = Party.objects.filter(pk=fixed_contract.supplier_id)
            # Supplier and contract come from the contract page: show them, do not let them drift.
            self.fields["supplier"].disabled = True
            self.fields["contract"].disabled = True
            self.fields["contract"].label = "Договор"
            self.fields["specification_number"].label = "Номер спецификации"
            self.fields["specification_number"].help_text = "Как в бумажной спецификации: 1, 2, 3…"
            self.fields["product"].queryset = products.filter(
                Q(kind=Product.Kind.GRAIN) | Q(purchase_lines__order__contract=fixed_contract)
            ).distinct()
            self.fields["product"].label = "Зерно"
            self.fields["product"].help_text = "В списке товары с типом «Зерно»."
            self.fields["quantity"].label = "Плановый вес, кг"
            self.fields["quantity"].help_text = "Например 1 000 000 кг = 1 000 т."
            self.fields["price"].label = "Цена за кг"
            if not self.initial.get("currency"):
                self.fields["currency"].initial = fixed_contract.currency
            self.fields["currency"].help_text = "По умолчанию валюта договора."
            if fixed_contract.delivery_term_id and not self.initial.get("delivery_term"):
                self.fields["delivery_term"].initial = fixed_contract.delivery_term_id
        else:
            self.fields["product"].queryset = products.exclude(kind=Product.Kind.GRAIN)
            self.fields["product"].help_text = "Зерно здесь не заказывают: оно идёт по договору и спецификации."
            self.fields["quantity"].help_text = "В единице товара: кг, шт, л или мешки."
            self.fields["price"].label = "Цена за единицу"
            for name in ("contract", "specification_number", "tolerance_percent", "delivery_term"):
                self.fields[name].widget = forms.HiddenInput()
        self.fields["product"].label_from_instance = _product_label

    def clean(self):
        cleaned = super().clean()
        contract = self.fixed_contract or cleaned.get("contract")
        supplier = cleaned.get("supplier")
        spec = (cleaned.get("specification_number") or "").strip()
        cleaned["specification_number"] = spec
        cleaned["contract"] = contract
        if contract is not None:
            if supplier and contract.supplier_id != supplier.pk:
                self.add_error("supplier", "Поставщик закупки должен совпадать с поставщиком договора.")
            if not spec:
                self.add_error("specification_number", "Для спецификации нужен номер в рамках договора.")
        elif spec:
            self.add_error("specification_number", "Номер спецификации указывают только для закупки по договору.")
        product = cleaned.get("product")
        quantity = cleaned.get("quantity")
        if product is not None and contract is None and product.kind == Product.Kind.GRAIN:
            self.add_error(
                "product",
                "Зерно покупается по договору: откройте договор и нажмите «Добавить спецификацию».",
            )
        if product is not None and quantity is not None:
            try:
                ensure_whole(product, quantity)
            except ValidationError as exc:
                self.add_error("quantity", error_text(exc))
        cleaned["bags"] = _legacy_bags(product, quantity, self)
        return cleaned


def _product_label(product):
    unit = unit_label(product.unit)
    pack = f", {product.pack_label}" if product.pack_label else ""
    return f"{product.name} ({unit}{pack})"


def _legacy_bags(product, quantity, form):
    """Old products counted in kg with a sack mass: the number of sacks follows from the weight."""
    if product is None or quantity is None or not (product.unit == Product.Unit.KG and product.package_kg):
        return None
    bags = quantity / product.package_kg
    if bags != bags.to_integral_value():
        form.add_error("quantity", f"Вес должен делиться на мешки по {format_qty(product.package_kg)} кг.")
        return None
    return int(bags)


def _orders():
    return PurchaseOrder.objects.select_related("document", "supplier", "contract").order_by(
        "-document__effective_date", "-pk"
    )


def _attach_figures(orders):
    rows = list(orders)
    figs = order_figures([row.pk for row in rows])
    for row in rows:
        row.fig = figs[row.pk]
    return rows


@erp_page
def purchase_list(request):
    remember_list(request, "purchases")
    qs = _orders()
    q = request.GET.get("q", "").strip()
    supplier = request.GET.get("supplier", "")
    status = request.GET.get("status", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if q:
        qs = qs.filter(
            Q(document__number__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(specification_number__icontains=q)
            | Q(contract__number__icontains=q)
        )
    if supplier:
        qs = qs.filter(supplier_id=supplier)
    if status == "open":
        qs = qs.filter(document__reversal__isnull=True)
    elif status == "reversed":
        qs = qs.filter(document__reversal__isnull=False)
    if date_from:
        qs = qs.filter(document__effective_date__gte=date_from)
    if date_to:
        qs = qs.filter(document__effective_date__lte=date_to)
    page, query = pager(request, qs)
    page.object_list = _attach_figures(page.object_list)
    return render(
        request,
        "ui/purchase_list.html",
        {
            "page": page,
            "query": query,
            "q": q,
            "supplier": supplier,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "suppliers": Party.objects.filter(is_supplier=True).order_by("name"),
        },
    )


def _purchase_from_form(form, actor):
    data = form.cleaned_data
    extra = {}
    if data.get("tolerance_percent") is not None:
        extra["tolerance_percent"] = data["tolerance_percent"]
    if data.get("delivery_term") is not None:
        extra["delivery_term"] = data["delivery_term"]
    return record_purchase(
        supplier=data["supplier"],
        effective_date=data["effective_date"],
        lines=[
            {
                "product": data["product"],
                "quantity": data["quantity"],
                "price": data["price"],
                "bags": data.get("bags"),
            }
        ],
        note=data.get("note") or "",
        actor=actor,
        contract=data.get("contract"),
        specification_number=data.get("specification_number") or "",
        currency=data["currency"],
        **extra,
    )


@erp_page
def purchase_create(request):
    form = PurchaseForm(request.POST or None)
    preview = _purchase_preview(request.POST) if request.method == "POST" else None
    if request.method == "POST" and request.POST.get("action") == "post" and form.is_valid():
        try:
            order = _purchase_from_form(form, request.user)
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(
                request,
                f"Закупка {order.document.number} проведена. Это план: остаток и долг появятся при приёмке.",
            )
            return redirect("purchase_detail", order.pk)
    return render(request, "ui/purchase_form.html", {"form": form, "preview": preview, "contract": None})


@erp_page
def specification_create(request, pk):
    contract = get_object_or_404(PurchaseContract, pk=pk)
    form = PurchaseForm(request.POST or None, fixed_contract=contract)
    preview = _purchase_preview(request.POST) if request.method == "POST" else None
    if request.method == "POST" and request.POST.get("action") == "post" and form.is_valid():
        try:
            order = _purchase_from_form(form, request.user)
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, f"Спецификация {order.specification_number} проведена.")
            return redirect("purchase_detail", order.pk)
    return render(request, "ui/purchase_form.html", {"form": form, "preview": preview, "contract": contract})


def _purchase_preview(data):
    try:
        quantity = LooseDecimalField(max_digits=18, decimal_places=3).clean(data.get("quantity"))
        price = LooseDecimalField(max_digits=18, decimal_places=4).clean(data.get("price"))
    except (forms.ValidationError, TypeError, KeyError):
        return None
    if not quantity or not price:
        return None
    currency = data.get("currency") or ""
    if currency not in PurchaseOrder.Currency.values:
        currency = ""
    return f"Расчётная сумма: {format_money(line_amount(quantity, price))} {currency}".strip()


@erp_page
def purchase_edit(request, pk):
    order = get_object_or_404(_orders().prefetch_related("lines"), pk=pk)
    line = order.lines.first()
    initial = {
        "supplier": order.supplier_id,
        "effective_date": order.document.effective_date,
        "contract": order.contract_id,
        "specification_number": order.specification_number,
        "product": line.product_id if line else None,
        "quantity": line.quantity if line else None,
        "price": line.price if line else None,
        "currency": order.currency,
        "bags": line.bags if line else None,
        "tolerance_percent": order.tolerance_percent,
        "delivery_term": order.delivery_term_id,
        "note": order.document.note,
    }
    form = PurchaseForm(request.POST or None, initial=initial, fixed_contract=order.contract)
    form.fields["supplier"].disabled = True
    form.fields["effective_date"].disabled = True
    form.fields["contract"].disabled = True
    form.fields["note"].disabled = True
    form.fields["note"].help_text = "Комментарий проведённого документа не меняется."
    if line is not None:
        form.fields["product"].queryset = Product.objects.filter(
            Q(active=True) | Q(pk=line.product_id)
        ).order_by("name")
    from apps.inventory.models import ReceiptLine

    moved = (
        order.shipments.filter(status=Shipment.Status.POSTED).exists()
        or ReceiptLine.objects.filter(purchase_line__order=order, receipt__document__state=Document.State.POSTED).exists()
    )
    if moved:
        for name in ("specification_number", "product", "quantity", "price", "currency", "bags"):
            form.fields[name].disabled = True
        form.fields["product"].help_text = (
            "Товар, количество, цена и валюта заблокированы: по закупке уже есть проведённые поставки или приёмки. "
            "Чтобы их изменить, сначала отмените выполнение поставок."
        )
    if request.method == "POST" and request.POST.get("action") == "post" and form.is_valid():
        data = form.cleaned_data
        bags = data.get("bags") or None
        changed = (
            line is None
            or line.product_id != data["product"].pk
            or line.quantity != data["quantity"]
            or line.price != data["price"]
            or (line.bags or None) != bags
            or order.currency != data["currency"]
            or (order.specification_number or "") != (data.get("specification_number") or "")
        )
        changes = {"actor": request.user}
        if data.get("tolerance_percent") is not None:
            changes["tolerance_percent"] = data["tolerance_percent"]
        if data.get("delivery_term") is not None:
            changes["delivery_term"] = data["delivery_term"]
        if changed:
            changes["lines"] = [
                {
                    "product": data["product"],
                    "quantity": data["quantity"],
                    "price": data["price"],
                    "bags": bags,
                }
            ]
            changes["specification_number"] = data.get("specification_number") or ""
            changes["currency"] = data["currency"]
        try:
            update_specification(order, **changes)
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Запись сохранена. Склад и долг от этого не меняются.")
            return redirect("purchase_detail", order.pk)
    return render(
        request,
        "ui/purchase_form.html",
        {"form": form, "preview": None, "contract": order.contract, "editing": order},
    )


@erp_page
@require_POST
def purchase_delete(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    contract_id = order.contract_id
    try:
        delete_specification(order, actor=request.user)
    except ValidationError as exc:
        messages.error(request, error_text(exc))
        return redirect("purchase_detail", pk)
    if contract_id:
        messages.success(request, "Спецификация удалена.")
        return redirect("contract_detail", contract_id)
    messages.success(request, "Заказ удалён.")
    return redirect("materials_monitor")


@erp_page
def purchase_detail(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    order.fig = order_figures([order.pk])[order.pk]
    order.ui_percent = fill_percent(order.fig["planned_qty"], order.fig["accepted_qty"])
    lines = order.lines.select_related("product")
    return render(
        request,
        "ui/purchase_detail.html",
        {
            "order": order,
            "lines": lines,
            "statement": specification_statement(order),
            "reversed": Document.objects.filter(reverses=order.document).exists(),
            "posted_shipments": order.shipments.filter(status=Shipment.Status.POSTED).exists(),
            "back_url": stored_back(request, "wheat" if order.contract_id else "purchases", "/purchases/"),
        },
    )


@erp_page
def contract_list(request):
    remember_list(request, "contracts")
    qs = PurchaseContract.objects.select_related("supplier", "delivery_term").order_by("-contract_date", "-pk")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(supplier__name__icontains=q))
    page, query = pager(request, qs)
    rows = list(page.object_list)
    for contract in rows:
        contract.spec_count = contract.specifications.count()
    page.object_list = rows
    return render(request, "ui/contract_list.html", {"page": page, "query": query, "q": q})


@erp_page
def contract_create(request):
    form = ContractForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            contract = record_contract(
                supplier=data["supplier"],
                number=data["number"],
                contract_date=data["contract_date"],
                description=data.get("description") or "",
                active=data.get("active", True),
                currency=data.get("currency") or Currency.KGS,
                delivery_term=data.get("delivery_term"),
                end_date=data.get("end_date"),
                volume_tons=data.get("volume_tons"),
                amount_limit=data.get("amount_limit"),
                prepayment_percent=data.get("prepayment_percent"),
                payment_terms=data.get("payment_terms") or "",
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Договор сохранён.")
            return redirect("contract_detail", contract.pk)
    return render(request, "ui/contract_form.html", {"form": form, "contract": None})


@erp_page
def contract_edit(request, pk):
    contract = get_object_or_404(PurchaseContract, pk=pk)
    form = ContractForm(request.POST or None, instance=contract)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Договор сохранён.")
            return redirect("contract_detail", contract.pk)
    return render(request, "ui/contract_form.html", {"form": form, "contract": contract})


@erp_page
def contract_detail(request, pk):
    contract = get_object_or_404(
        PurchaseContract.objects.select_related("supplier", "delivery_term"),
        pk=pk,
    )
    specs = _attach_figures(
        contract.specifications.select_related("document", "supplier", "contract")
        .prefetch_related("lines")
        .order_by("specification_number")
    )
    total = {
        "planned_kg": sum((spec.fig["planned_qty"] or 0 for spec in specs), Decimal("0")),
        "accepted_kg": sum((spec.fig["accepted_qty"] or 0 for spec in specs), Decimal("0")),
        "accepted_amount": sum((spec.fig["accepted_amount"] or 0 for spec in specs), Decimal("0")),
        "paid": sum((spec.fig["paid"] or 0 for spec in specs), Decimal("0")),
        "outstanding": sum((spec.fig["outstanding"] or 0 for spec in specs), Decimal("0")),
    }
    if contract.volume_tons:
        total["volume_percent"] = round(total["accepted_kg"] / (contract.volume_tons * 1000) * 100, 1)
    if contract.amount_limit:
        total["limit_left"] = contract.amount_limit - total["accepted_amount"]
    return render(
        request,
        "ui/contract_detail.html",
        {
            "contract": contract,
            "specs": specs,
            "total": total,
            "back_url": stored_back(request, "contracts", "/contracts/"),
        },
    )


@erp_page
@require_POST
def contract_delete(request, pk):
    from apps.ui.http import remove_or_disable

    contract = get_object_or_404(PurchaseContract, pk=pk)
    return remove_or_disable(request, contract, name=contract.number, back="contract_list")


@erp_page
def specification_list(request):
    remember_list(request, "specs")
    qs = _orders().filter(contract__isnull=False).prefetch_related("lines")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(
            Q(specification_number__icontains=q)
            | Q(contract__number__icontains=q)
            | Q(supplier__name__icontains=q)
        )
    if status in PurchaseOrder.OperationalStatus.values:
        qs = qs.filter(operational_status=status)
    page, query = pager(request, qs)
    rows = _with_percent(_attach_figures(page.object_list))
    for order in rows:
        order.ui_lines = list(order.lines.all())
    page.object_list = rows
    return render(
        request,
        "ui/specification_list.html",
        {
            "page": page,
            "query": query,
            "q": q,
            "status": status,
            "statuses": PurchaseOrder.OperationalStatus.choices,
        },
    )


def _with_percent(orders):
    for order in orders:
        order.ui_percent = fill_percent(order.fig["planned_qty"], order.fig["accepted_qty"])
    return orders


@erp_page
def specification_start(request):
    """Pick an active contract, then open the existing specification form."""
    contracts = PurchaseContract.objects.filter(active=True).select_related("supplier").order_by("-contract_date", "-pk")
    if request.method == "POST":
        contract = get_object_or_404(contracts, pk=request.POST.get("contract") or 0)
        return redirect("specification_create", contract.pk)
    return render(request, "ui/specification_start.html", {"contracts": contracts})


@erp_page
@require_POST
def specification_status(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    action = request.POST.get("action") or ""
    noun = "Спецификация" if order.contract_id else "Заказ"
    try:
        if action == "complete":
            complete_specification(order, actor=request.user)
            if order.contract_id:
                messages.success(
                    request,
                    "Спецификация отмечена выполненной. Новую поставку добавить нельзя. Склад и долг не изменились.",
                )
            else:
                messages.success(
                    request,
                    "Заказ отмечен выполненным. Новую приёмку провести нельзя. Склад и долг не изменились.",
                )
        elif action == "reopen":
            reopen_specification(order, actor=request.user)
            messages.success(request, f"{noun} снова в работе.")
        else:
            messages.error(request, "Укажите выполнение или возврат в работу.")
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    return redirect("purchase_detail", order.pk)
