from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models import Document, Party
from apps.core.quantities import line_amount
from apps.finance.models import MoneyDocument, OpenItem
from apps.finance.queries import item_remaining, party_position
from apps.inventory.models import GoodsReceipt, Product
from apps.procurement.models import PurchaseContract, PurchaseOrder
from apps.procurement.services import record_contract, record_purchase
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
from apps.ui.http import erp_page, error_text, pager


class ContractForm(StyledModelForm):
    class Meta:
        model = PurchaseContract
        fields = ["supplier", "number", "contract_date", "description", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Party.objects.filter(is_supplier=True, active=True)
        if self.instance.pk and self.instance.supplier_id:
            suppliers = Party.objects.filter(Q(pk=self.instance.supplier_id) | Q(is_supplier=True, active=True))
        self.fields["supplier"].queryset = suppliers.order_by("name")
        self.fields["contract_date"].label = "Дата договора"
        if self.instance.pk and self.instance.specifications.exists():
            self.fields["supplier"].disabled = True
            self.fields["number"].disabled = True
            self.fields["number"].help_text = "У договора со спецификациями нельзя менять поставщика или номер."


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
        if fixed_contract is not None:
            self.fields["contract"].initial = fixed_contract.pk
            self.fields["contract"].queryset = PurchaseContract.objects.filter(pk=fixed_contract.pk)
            self.fields["supplier"].initial = fixed_contract.supplier_id
            self.fields["supplier"].queryset = Party.objects.filter(pk=fixed_contract.supplier_id)

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
        if product and product.kind == Product.Kind.FLOUR and product.unit == Product.Unit.KG and not cleaned.get("bags"):
            self.add_error("bags", "Для муки в килограммах укажите число мешков.")
        if product and product.kind != Product.Kind.FLOUR:
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
        },
    )


@erp_page
def contract_list(request):
    qs = PurchaseContract.objects.select_related("supplier").order_by("-contract_date", "-pk")
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
    contract = get_object_or_404(PurchaseContract.objects.select_related("supplier"), pk=pk)
    specs = _attach_figures(contract.specifications.select_related("document", "supplier", "contract"))
    return render(request, "ui/contract_detail.html", {"contract": contract, "specs": specs})
