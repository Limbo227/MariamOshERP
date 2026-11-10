from decimal import Decimal

from django import forms

from apps.catalog.models import Product
from apps.inventory.models import OpeningLine, StorageLocation, Warehouse


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
