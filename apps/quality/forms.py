from decimal import Decimal
from uuid import uuid4

from django import forms


def _style(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"


class LocalQualityForm(forms.Form):
    parameter = forms.CharField(label="Показатель", max_length=80)
    number = forms.DecimalField(label="Местное число", max_digits=12, decimal_places=3)
    unit = forms.CharField(label="Единица", max_length=20, required=False)
    comment = forms.CharField(label="Комментарий", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class ReleaseForm(forms.Form):
    quantity = forms.DecimalField(label="Допустить, кг", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)
    reason = forms.CharField(label="Основание", max_length=200)
    released_on = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)
