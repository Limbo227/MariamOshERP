from decimal import Decimal

from django import forms

from apps.catalog.models import Product


def _style(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"


class ProductForm(forms.Form):
    name = forms.CharField(label="Название", max_length=160)
    kind = forms.ChoiceField(label="Тип", choices=Product.Kind.choices)
    unit = forms.ChoiceField(label="Единица", choices=Product.Unit.choices)
    grade = forms.CharField(label="Сорт или класс", max_length=40, required=False)
    package_kg = forms.DecimalField(label="Масса мешка, кг", max_digits=10, decimal_places=3, required=False, min_value=Decimal("0.001"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        unit = data.get("unit")
        package = data.get("package_kg")
        if kind in (Product.Kind.WHEAT, Product.Kind.BYPRODUCT) and unit and unit != Product.Unit.KG:
            self.add_error("unit", "Этот товар учитывается в килограммах.")
        if kind == Product.Kind.SACK and unit and unit != Product.Unit.PCS:
            self.add_error("unit", "Мешок учитывается в штуках.")
        if kind == Product.Kind.FLOUR:
            if unit and unit != Product.Unit.KG:
                self.add_error("unit", "Мука учитывается в килограммах.")
            if not package:
                self.add_error("package_kg", "Укажите массу мешка.")
        elif package:
            self.add_error("package_kg", "Масса мешка нужна только для муки.")
        return data


class StationForm(forms.Form):
    name = forms.CharField(label="Станция", max_length=80)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class CounterpartyForm(forms.Form):
    name = forms.CharField(label="Название", max_length=160)
    is_supplier = forms.BooleanField(label="Поставщик", required=False, initial=True)
    is_customer = forms.BooleanField(label="Покупатель", required=False)
    is_other = forms.BooleanField(label="Прочие", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def clean(self):
        data = super().clean()
        if not (data.get("is_supplier") or data.get("is_customer") or data.get("is_other")):
            raise forms.ValidationError("Нужна хотя бы одна роль: поставщик, покупатель или прочие.")
        return data
