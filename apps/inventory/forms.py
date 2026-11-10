from decimal import Decimal
from uuid import uuid4

from django import forms

from apps.catalog.models import Product, Supplier
from apps.inventory.models import OpeningLine, StorageLocation, Warehouse
from apps.procurement.models import PurchaseOrder


class OpeningHeaderForm(forms.Form):
    reference = forms.CharField(label="Основание", max_length=160)
    effective_date = forms.DateField(
        label="Дата остатков",
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"


class OpeningLineForm(forms.Form):
    product = forms.ModelChoiceField(label="Товар", queryset=Product.objects.none())
    location = forms.ModelChoiceField(label="Место", queryset=StorageLocation.objects.none())
    quantity = forms.DecimalField(label="Количество", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)
    bags = forms.IntegerField(label="Мешки", required=False, min_value=1)
    basis = forms.ChoiceField(label="Основание", choices=OpeningLine.Basis.choices)

    def __init__(self, *args, company, warehouse, **kwargs):
        super().__init__(*args, **kwargs)
        finished = warehouse.kind == Warehouse.Kind.FINISHED
        if finished:
            kinds = [Product.Kind.FLOUR, Product.Kind.BYPRODUCT]
        else:
            kinds = [Product.Kind.WHEAT, Product.Kind.SACK, Product.Kind.MATERIAL]
        self.fields["product"].queryset = Product.objects.filter(company=company, active=True, kind__in=kinds).order_by("name")
        self.fields["location"].queryset = StorageLocation.objects.filter(warehouse=warehouse, active=True).order_by("name")
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"


OpeningLineFormSet = forms.formset_factory(OpeningLineForm, extra=3, min_num=1, validate_min=True)


class ReceiptHeaderForm(forms.Form):
    supplier = forms.ModelChoiceField(label="Поставщик", queryset=Supplier.objects.none())
    order = forms.ModelChoiceField(label="Заказ", queryset=PurchaseOrder.objects.none(), required=False)
    reference = forms.CharField(label="Основание", max_length=160)
    effective_date = forms.DateField(label="Дата приёмки", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(company=company, active=True).order_by("name")
        self.fields["order"].queryset = PurchaseOrder.objects.filter(company=company, state=PurchaseOrder.State.CONFIRMED).order_by("-pk")
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"


class ReceiptLineForm(forms.Form):
    product = forms.ModelChoiceField(label="Товар", queryset=Product.objects.none(), required=False)
    location = forms.ModelChoiceField(label="Место", queryset=StorageLocation.objects.none(), required=False)
    quantity = forms.DecimalField(label="Количество", min_value=Decimal("0.001"), max_digits=18, decimal_places=3, required=False)
    basis = forms.ChoiceField(label="Основание", choices=OpeningLine.Basis.choices, required=False)
    batch_reference = forms.CharField(label="Партия", max_length=80, required=False)

    def __init__(self, *args, company, warehouse, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            company=company, active=True, kind__in=[Product.Kind.WHEAT, Product.Kind.SACK, Product.Kind.MATERIAL]
        ).order_by("name")
        self.fields["location"].queryset = StorageLocation.objects.filter(warehouse=warehouse, active=True).order_by("name")
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"

    def clean(self):
        data = super().clean()
        if not any(data.get(name) for name in ("product", "location", "quantity")):
            return {}
        if not data.get("product") or not data.get("location") or not data.get("quantity") or not data.get("basis"):
            raise forms.ValidationError("В строке нужны товар, место, количество и основание.")
        return data


ReceiptLineFormSet = forms.formset_factory(ReceiptLineForm, extra=3, min_num=1, validate_min=True)


class AdjustmentForm(forms.Form):
    product = forms.ModelChoiceField(label="Товар", queryset=Product.objects.none())
    location = forms.ModelChoiceField(label="Место", queryset=StorageLocation.objects.none())
    quantity = forms.DecimalField(label="Изменение", max_digits=18, decimal_places=3)
    basis = forms.ChoiceField(label="Основание", choices=OpeningLine.Basis.choices)
    reason = forms.CharField(label="Причина", max_length=200)
    effective_date = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, company, warehouse, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(company=company, active=True).order_by("name")
        self.fields["location"].queryset = StorageLocation.objects.filter(warehouse=warehouse, active=True).order_by("name")
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"

    def clean_quantity(self):
        value = self.cleaned_data["quantity"]
        if value == 0:
            raise forms.ValidationError("Изменение не может быть нулевым.")
        return value
