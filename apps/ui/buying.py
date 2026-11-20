from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Currency, Document, Party
from apps.core.quantities import line_amount
from apps.finance.models import MoneyDocument, OpenItem
from apps.finance.queries import item_remaining, party_position
from apps.inventory.models import GoodsReceipt, Product
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
from apps.ui.figures import order_figures
from apps.ui.formatting import format_money
from apps.ui.http import erp_page, error_text, pager, remember_list, stored_back


class ContractForm(StyledModelForm):
    class Meta:
        model = PurchaseContract
        fields = ["supplier", "number", "contract_date", "currency", "delivery_term", "description", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Party.objects.filter(is_supplier=True, active=True)
        if self.instance.pk and self.instance.supplier_id:
            suppliers = Party.objects.filter(Q(pk=self.instance.supplier_id) | Q(is_supplier=True, active=True))
        self.fields["supplier"].queryset = suppliers.order_by("name")
        self.fields["contract_date"].label = "Дата договора"
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
        self.fields["contract"].empty_label = "Без договора — обычная закупка"
        self.fields["product"].queryset = Product.objects.filter(active=True).order_by("name")
        self.fields["specification_number"].help_text = "Только для закупки по договору."
        self.fields["bags"].help_text = "Только для муки: число мешков."
        self.fields["delivery_term"].queryset = DeliveryTerm.objects.filter(active=True).order_by("name")
        self.fields["tolerance_percent"].help_text = "Справочный допуск. Не мешает провести поставку и не мешает закрыть спецификацию."
        if fixed_contract is not None:
            self.fields["contract"].initial = fixed_contract.pk
            self.fields["contract"].queryset = PurchaseContract.objects.filter(pk=fixed_contract.pk)
            self.fields["supplier"].initial = fixed_contract.supplier_id
            self.fields["supplier"].queryset = Party.objects.filter(pk=fixed_contract.supplier_id)
            self.fields["quantity"].label = "Плановый вес, кг"
            self.fields["price"].label = "Цена за кг"
            if not self.initial.get("currency"):
                self.fields["currency"].initial = fixed_contract.currency
            self.fields["currency"].help_text = "По умолчанию валюта договора."
            if fixed_contract.delivery_term_id and not self.initial.get("delivery_term"):
                self.fields["delivery_term"].initial = fixed_contract.delivery_term_id
        else:
            self.fields["tolerance_percent"].widget = forms.HiddenInput()
            self.fields["delivery_term"].widget = forms.HiddenInput()

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
        counts_bags = product and product.unit == Product.Unit.KG and product.package_kg
        if counts_bags and not cleaned.get("bags"):
            self.add_error("bags", "Для товара с массой мешка укажите число мешков.")
        if product and not counts_bags and product.unit != Product.Unit.BAG:
            cleaned["bags"] = None
        return cleaned


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
    messages.success(request, "Спецификация удалена.")
    if contract_id:
        return redirect("contract_detail", contract_id)
    return redirect("specification_list")


@erp_page
def purchase_detail(request, pk):
    order = get_object_or_404(_orders(), pk=pk)
    order.fig = order_figures([order.pk])[order.pk]
    lines = order.lines.select_related("product")
    shipments = order.shipments.all()
    receipts = (
        GoodsReceipt.objects.filter(lines__purchase_line__order=order)
        .select_related("document", "warehouse")
        .distinct()
    )
    payments = (
        MoneyDocument.objects.filter(Q(order=order) | Q(document__allocations__we_owe__order=order))
        .select_related("document", "account", "operation", "party")
        .distinct()
    )
    debts = []
    for item in OpenItem.objects.filter(order=order, lane=OpenItem.Lane.PAYABLE).select_related("document"):
        debts.append({"item": item, "left": item_remaining(item)})
    position = party_position(order.supplier)["payable"]
    return render(
        request,
        "ui/purchase_detail.html",
        {
            "order": order,
            "lines": lines,
            "shipments": shipments,
            "receipts": receipts,
            "payments": payments,
            "debts": debts,
            "position": position,
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
    specs = _attach_figures(contract.specifications.select_related("document", "supplier", "contract"))
    return render(
        request,
        "ui/contract_detail.html",
        {"contract": contract, "specs": specs, "back_url": stored_back(request, "contracts", "/contracts/")},
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
    qs = _orders().filter(contract__isnull=False)
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
    page.object_list = _attach_figures(page.object_list)
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


@erp_page
@require_POST
def specification_status(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    action = request.POST.get("action") or ""
    try:
        if action == "complete":
            complete_specification(order, actor=request.user)
            messages.success(request, "Спецификация отмечена выполненной. Склад и долг не изменились.")
        elif action == "reopen":
            reopen_specification(order, actor=request.user)
            messages.success(request, "Спецификация снова в работе.")
        else:
            messages.error(request, "Укажите выполнение или возврат в работу.")
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    return redirect("purchase_detail", order.pk)
