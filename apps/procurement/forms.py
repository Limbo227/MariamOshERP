from decimal import Decimal
from uuid import uuid4

from django import forms

from apps.catalog.models import OriginStation, Product, Supplier
from apps.inventory.models import OpeningLine, StorageLocation, Warehouse
from apps.procurement.models import (
    ChargePayment,
    ContractLine,
    ContractShipment,
    CustomsAcceptance,
    OrderLine,
    PurchaseOrder,
    Shipment,
    SupplyContract,
)
from apps.settlements.models import SupplierPayment


def _style(form):
    for field in form.fields.values():
        field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"


class OrderHeaderForm(forms.Form):
    supplier = forms.ModelChoiceField(label="Поставщик", queryset=Supplier.objects.none())
    reference = forms.CharField(label="Основание", max_length=160)
    contract_reference = forms.CharField(label="Договор", max_length=80, required=False)
    batch_number = forms.CharField(label="Партия", max_length=80, required=False)
    wagon_count = forms.IntegerField(label="Вагоны", min_value=1, required=False)
    effective_date = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(company=company, active=True).order_by("name")
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)


class OrderLineForm(forms.Form):
    product = forms.ModelChoiceField(label="Товар", queryset=Product.objects.none(), required=False)
    quantity = forms.DecimalField(label="Количество", min_value=Decimal("0.001"), max_digits=18, decimal_places=3, required=False)
    unit_price = forms.DecimalField(label="Цена, KGS", min_value=Decimal("0.0001"), max_digits=18, decimal_places=4, required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            company=company, active=True, kind__in=[Product.Kind.WHEAT, Product.Kind.SACK, Product.Kind.MATERIAL]
        ).order_by("name")
        _style(self)

    def clean(self):
        data = super().clean()
        if not data.get("product") and not data.get("quantity") and not data.get("unit_price"):
            return {}
        if not data.get("product") or not data.get("quantity") or not data.get("unit_price"):
            raise forms.ValidationError("В строке нужны товар, количество и цена.")
        return data


OrderLineFormSet = forms.formset_factory(OrderLineForm, extra=2, min_num=1, validate_min=True)


class AmendmentForm(forms.Form):
    reason = forms.CharField(label="Причина", max_length=200)
    effective_date = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])

    def __init__(self, *args, lines, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_lines = list(lines)
        for line in self.order_lines:
            self.fields[f"quantity_{line.pk}"] = forms.DecimalField(label=f"Новое количество: {line.product.name}", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)
            self.fields[f"price_{line.pk}"] = forms.DecimalField(label=f"Новая цена: {line.product.name}", min_value=Decimal("0.0001"), max_digits=18, decimal_places=4)
        _style(self)

    def terms(self):
        return [(line.pk, self.cleaned_data[f"quantity_{line.pk}"], self.cleaned_data[f"price_{line.pk}"]) for line in self.order_lines]


class PaymentForm(forms.Form):
    amount = forms.DecimalField(label="Сумма, KGS", min_value=Decimal("0.01"), max_digits=18, decimal_places=2)
    external_reference = forms.CharField(label="Внешняя ссылка", max_length=80)
    method = forms.ChoiceField(label="Куда", choices=SupplierPayment.Method.choices)
    paid_on = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)


class ShipmentForm(forms.Form):
    supplier = forms.ModelChoiceField(label="Поставщик", queryset=Supplier.objects.none())
    order = forms.ModelChoiceField(label="Заказ", queryset=PurchaseOrder.objects.none(), required=False)
    reference = forms.CharField(label="Партия поставщика", max_length=80)
    customs_port = forms.CharField(label="Таможня", max_length=80, required=False)
    expected_date = forms.DateField(label="Ожидается", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(company=company, active=True).order_by("name")
        self.fields["order"].queryset = PurchaseOrder.objects.filter(company=company, state=PurchaseOrder.State.CONFIRMED).order_by("-pk")
        _style(self)


class WagonForm(forms.Form):
    identifier = forms.CharField(label="Номер вагона", max_length=40)
    declared_quantity = forms.DecimalField(label="Заявлено", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class ChargeForm(forms.Form):
    counterparty = forms.CharField(label="Кому", max_length=160)
    amount = forms.DecimalField(label="Сумма расхода, KGS", min_value=Decimal("0.01"), max_digits=18, decimal_places=2)
    charged_on = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    note = forms.CharField(label="Назначение", max_length=160, required=False)
    method = forms.ChoiceField(label="Оплата", choices=ChargePayment.Method.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class PassportForm(forms.Form):
    parameter = forms.CharField(label="Показатель", max_length=80)
    number = forms.DecimalField(label="Число", max_digits=12, decimal_places=3, required=False)
    unit = forms.CharField(label="Единица", max_length=20, required=False)
    passport_version = forms.CharField(label="Паспорт", max_length=40, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def clean(self):
        data = super().clean()
        if data.get("number") is None:
            raise forms.ValidationError("Нужно число паспорта.")
        return data


class CustomsAcceptForm(forms.Form):
    port = forms.CharField(label="Таможенный пост", max_length=80)
    quantity = forms.DecimalField(label="Принято", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)
    accepted_on = forms.DateField(label="Дата", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class StorageReceiveForm(forms.Form):
    acceptance = forms.ModelChoiceField(label="Отметка таможни", queryset=CustomsAcceptance.objects.none(), required=False)
    line = forms.ModelChoiceField(label="Строка заказа", queryset=OrderLine.objects.none(), required=False)
    location = forms.ModelChoiceField(label="Место", queryset=StorageLocation.objects.none())
    quantity = forms.DecimalField(label="Принято", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)
    basis = forms.ChoiceField(label="Основание", choices=OpeningLine.Basis.choices)

    def __init__(self, *args, acceptances, lines, locations, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["acceptance"].queryset = acceptances
        self.fields["line"].queryset = lines
        self.fields["location"].queryset = locations
        if acceptances.count() == 1:
            self.fields["acceptance"].initial = acceptances.get().pk
            self.fields["acceptance"].widget = forms.HiddenInput()
        elif acceptances.count() > 1:
            self.fields["acceptance"].required = True
        if lines.count() == 1:
            self.fields["line"].initial = lines.get().pk
            self.fields["line"].widget = forms.HiddenInput()
        elif lines.count() > 1:
            self.fields["line"].required = True
        _style(self)


class ShipmentStateForm(forms.Form):
    state = forms.ChoiceField(label="Состояние", choices=Shipment.State.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class ContractForm(forms.Form):
    supplier = forms.ModelChoiceField(label="Поставщик", queryset=Supplier.objects.none())
    number = forms.CharField(label="Номер контракта", max_length=80)
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(company=company, active=True, is_supplier=True).order_by("name")
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)


class ContractLineForm(forms.Form):
    product = forms.ModelChoiceField(label="Товар", queryset=Product.objects.none(), required=False)
    quantity = forms.DecimalField(label="Количество", min_value=Decimal("0.001"), max_digits=18, decimal_places=3, required=False)
    price = forms.DecimalField(label="Цена", min_value=Decimal("0.0001"), max_digits=18, decimal_places=4, required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(company=company, active=True).order_by("name")
        self.fields["product"].empty_label = "—"
        _style(self)

    def clean(self):
        data = super().clean()
        if any(data.get(name) for name in ("product", "quantity", "price")) and not all(data.get(name) for name in ("product", "quantity", "price")):
            raise forms.ValidationError("В строке нужны товар, количество и цена.")
        return data


class BaseContractLineFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(form.cleaned_data.get("product") for form in self.forms):
            raise forms.ValidationError("Добавьте хотя бы одну строку: товар, количество и цена.")


ContractLineFormSet = forms.formset_factory(ContractLineForm, formset=BaseContractLineFormSet, extra=4, max_num=30)


class ContractShipmentForm(forms.Form):
    line = forms.ModelChoiceField(label="Строка", queryset=ContractLine.objects.none())
    station = forms.ModelChoiceField(label="Станция", queryset=OriginStation.objects.none())
    wagon_count = forms.IntegerField(label="Вагоны", min_value=1)
    quantity = forms.DecimalField(label="Количество", min_value=Decimal("0.001"), max_digits=18, decimal_places=3)
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, contract, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["line"].queryset = contract.lines.select_related("product")
        self.fields["line"].label_from_instance = lambda line: f"{line.position}. {line.product.name}"
        self.fields["station"].queryset = OriginStation.objects.filter(company=contract.company, active=True)
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)


class FactoryForm(forms.Form):
    shipment = forms.ModelChoiceField(label="Отгрузка", queryset=ContractShipment.objects.none())
    warehouse = forms.ModelChoiceField(label="Склад завода", queryset=Warehouse.objects.none())
    arrived_on = forms.DateField(label="Дата прибытия", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, contract, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shipment"].queryset = ContractShipment.objects.filter(line__contract=contract, factory_arrival__isnull=True).select_related("station", "line__product")
        self.fields["shipment"].label_from_instance = lambda shipment: f"{shipment.station.name}, {shipment.quantity} {shipment.line.product.get_unit_display()}"
        self.fields["warehouse"].queryset = Warehouse.objects.filter(company=contract.company)
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)


class ContractPayForm(forms.Form):
    paid_on = forms.DateField(label="Дата оплаты", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    amount = forms.DecimalField(label="Сумма, руб.", min_value=Decimal("0.01"), max_digits=18, decimal_places=2)
    key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["key"].initial = uuid4()
        _style(self)


class PaymentPageForm(ContractPayForm):
    contract = forms.ModelChoiceField(label="Контракт", queryset=SupplyContract.objects.none())

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contract"].queryset = SupplyContract.objects.filter(company=company).select_related("supplier").order_by("supplier__name", "number")
        self.fields["contract"].label_from_instance = lambda contract: f"{contract.supplier.name} — {contract.number}"
        self.order_fields(["contract", "paid_on", "amount"])
        _style(self)
