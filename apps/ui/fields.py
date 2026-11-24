from decimal import Decimal, InvalidOperation

from django import forms

INPUT = "mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-500"
BLANK = "— выберите —"


def _russian_blank(field):
    from django.db.models.utils import get_blank_choice_label

    default = str(get_blank_choice_label())
    if isinstance(field, forms.ModelChoiceField):
        if field.empty_label is not None and str(field.empty_label) in (default, "---------"):
            field.empty_label = BLANK
        return
    if isinstance(field, forms.ChoiceField):
        choices = list(field.choices)
        if choices and choices[0][0] == "" and str(choices[0][1]) in (default, "---------"):
            choices[0] = ("", BLANK)
            field.choices = choices


def style_fields(form):
    for name, field in form.fields.items():
        _russian_blank(field)
        if getattr(form, "_meta", None) is not None:
            field.error_messages["unique"] = f"«{field.label}» с таким значением уже есть. Укажите другое."
        widget = field.widget
        if isinstance(widget, forms.HiddenInput):
            continue
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = "h-4 w-4"
            continue
        widget.attrs["class"] = INPUT
        if isinstance(field, LooseDecimalField):
            # A text box accepts «0,23» and «1 000 000»; the field itself understands both.
            widget.input_type = "text"
            widget.attrs["inputmode"] = "decimal"
            widget.attrs.pop("step", None)
            widget.attrs["autocomplete"] = "off"
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
    from django.utils import timezone

    field = forms.DateField(label=label, required=required, initial=timezone.localdate if required else None)
    field.widget = forms.DateInput()
    return field
