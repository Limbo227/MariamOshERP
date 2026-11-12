from decimal import Decimal, InvalidOperation

from django import forms

INPUT = "mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"


def style_fields(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.HiddenInput):
            continue
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = "h-4 w-4"
            continue
        widget.attrs["class"] = INPUT
        if isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("rows", 3)
        if isinstance(field, forms.DateField):
            widget.input_type = "date"
            widget.format = "%Y-%m-%d"
            field.localize = False
            field.input_formats = ["%Y-%m-%d", "%d.%m.%Y"]


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class LooseDecimalField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(" ", "").replace(",", ".")
        try:
            return super().to_python(value)
        except InvalidOperation as exc:
            raise forms.ValidationError("Введите число.") from exc


def money_field(label, required=True):
    return LooseDecimalField(
        label=label,
        required=required,
        min_value=Decimal("0.01"),
        max_digits=18,
        decimal_places=2,
    )


def qty_field(label, required=True):
    return LooseDecimalField(
        label=label,
        required=required,
        min_value=Decimal("0.001"),
        max_digits=18,
        decimal_places=3,
    )


def price_field(label):
    return LooseDecimalField(
        label=label,
        min_value=Decimal("0.0001"),
        max_digits=18,
        decimal_places=4,
    )


def date_field(label, required=True):
    field = forms.DateField(label=label, required=required)
    field.widget = forms.DateInput()
    return field
