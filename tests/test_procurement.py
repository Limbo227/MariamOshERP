from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.core.models import Organization, Party
from apps.finance.models import OpenItem
from apps.inventory.models import Product, StockMove
from apps.procurement.models import PurchaseOrder, RailwayStation, Shipment
from apps.procurement.services import (
    record_contract,
    record_purchase,
    record_shipment,
)

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 2)


@pytest.fixture
def grain():
    Organization.objects.create(legal_name="Мариам-Ош")
    wheat = Product.objects.create(sku="WHEAT", name="Пшеница", kind=Product.Kind.WHEAT, unit=Product.Unit.KG)
    sack = Product.objects.create(sku="SACK", name="Мешок", kind=Product.Kind.SACK, unit=Product.Unit.PCS)
    supplier = Party.objects.create(name="Поставщик зерна", is_supplier=True)
    other = Party.objects.create(name="Другой поставщик", is_supplier=True)
    station = RailwayStation.objects.create(name="Манас")
    return {"wheat": wheat, "sack": sack, "supplier": supplier, "other": other, "station": station}


def _buy(grain, product, **kwargs):
    return record_purchase(
        supplier=kwargs.pop("supplier", grain["supplier"]),
        effective_date=DAY,
        lines=[{"product": product, "quantity": "1000", "price": "20"}],
        **kwargs,
    )


def test_contract_does_not_touch_stock_or_money(grain):
    before_stock = StockMove.objects.count()
    before_money = OpenItem.objects.count()
    contract = record_contract(supplier=grain["supplier"], number="З-2026", contract_date=DAY, description="Пшеница")
    assert contract.active is True
    assert StockMove.objects.count() == before_stock
    assert OpenItem.objects.count() == before_money


def test_ordinary_order_needs_no_contract_or_shipment(grain):
    order = _buy(grain, grain["sack"])
    assert order.contract_id is None
    assert order.specification_number == ""
    assert order.currency == PurchaseOrder.Currency.KGS
    assert order.shipments.exists() is False
    assert OpenItem.objects.filter(party=grain["supplier"], lane=OpenItem.Lane.PAYABLE).exists() is False


def test_specification_belongs_to_one_contract(grain):
    contract = record_contract(supplier=grain["supplier"], number="З-2026", contract_date=DAY)
    order = _buy(grain, grain["wheat"], contract=contract, specification_number="8", currency="RUB")
    assert order.contract == contract
    assert order.specification_number == "8"
    assert order.currency == "RUB"
    assert OpenItem.objects.filter(party=grain["supplier"]).exists() is False
    assert StockMove.objects.exists() is False


def test_specification_supplier_must_match_contract(grain):
    contract = record_contract(supplier=grain["supplier"], number="З-2026", contract_date=DAY)
    with pytest.raises(ValidationError):
        _buy(grain, grain["wheat"], supplier=grain["other"], contract=contract, specification_number="1")


def test_specification_number_is_unique_inside_contract(grain):
    contract = record_contract(supplier=grain["supplier"], number="З-2026", contract_date=DAY)
    _buy(grain, grain["wheat"], contract=contract, specification_number="8")
    with pytest.raises(ValidationError):
        _buy(grain, grain["wheat"], contract=contract, specification_number="8")
    other = record_contract(supplier=grain["other"], number="З-2026", contract_date=DAY)
    second = _buy(grain, grain["wheat"], supplier=grain["other"], contract=other, specification_number="8")
    assert second.specification_number == "8"


def test_inactive_contract_rejects_a_new_specification(grain):
    contract = record_contract(supplier=grain["supplier"], number="З-2026", contract_date=DAY, active=False)
    with pytest.raises(ValidationError):
        _buy(grain, grain["wheat"], contract=contract, specification_number="1")


def test_draft_shipment_does_not_create_stock_or_payable(grain):
    order = _buy(grain, grain["wheat"])
    payables = OpenItem.objects.count()
    first = record_shipment(
        order=order,
        quantity="68000",
        departure_date=DAY,
        wagon_number="125",
        departure_station=grain["station"],
    )
    second = record_shipment(
        order=order,
        quantity="1000",
        departure_date=DAY,
        departure_station=grain["station"],
        wagon_count=2,
    )
    assert first.status == Shipment.Status.DRAFT
    assert order.shipments.count() == 2
    assert second.wagon_number == ""
    assert StockMove.objects.exists() is False
    assert OpenItem.objects.count() == payables


def test_same_wagon_number_cannot_repeat_inside_one_shipment(grain):
    from apps.procurement.services import declare_wagons

    order = _buy(grain, grain["wheat"])
    shipment = record_shipment(
        order=order,
        quantity="68000",
        departure_date=DAY,
        departure_station=grain["station"],
        wagon_count=2,
    )
    with pytest.raises(ValidationError):
        declare_wagons(
            shipment,
            [{"wagon_number": "125", "weight_kg": "34000"}, {"wagon_number": "125", "weight_kg": "34000"}],
        )
