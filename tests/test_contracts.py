from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from apps.catalog.models import OriginStation
from apps.inventory.models import StockLedgerEntry
from apps.procurement.contracts import (
    add_contract_payment,
    add_shipment,
    contract_position,
    create_contract,
    create_counterparty,
    create_station,
    receive_at_factory,
)
from apps.procurement.models import SupplyContract
from apps.settlements.models import SupplierObligation
from tests.conftest import _person

pytestmark = pytest.mark.django_db

PERMS = [
    "core.view_workspace",
    "catalog.add_supplier",
    "catalog.view_supplier",
    "catalog.add_originstation",
    "catalog.view_originstation",
    "procurement.view_supplycontract",
    "procurement.add_supplycontract",
    "procurement.add_contractline",
    "procurement.add_contractshipment",
    "procurement.add_factoryarrival",
    "procurement.add_contractpayment",
]


def test_contract_cart_tracks_arrival_and_payment_without_stock(world):
    user, membership = _person("supply-book", world.company, PERMS, [world.raw])
    with pytest.raises(ValidationError, match="роль"):
        create_counterparty(membership=membership, actor=user, name="Пустой", is_supplier=False, is_customer=False, is_other=False)
    seller = create_counterparty(membership=membership, actor=user, name="Синтетика-Зерно", is_supplier=True, is_customer=False, is_other=False)
    buyer = create_counterparty(membership=membership, actor=user, name="Синтетика-Мука", is_supplier=False, is_customer=True, is_other=False)
    station = create_station(membership=membership, actor=user, name="КОСТАНАЙ")
    assert OriginStation.objects.filter(company=world.company, name="КОСТАНАЙ").count() == 1
    with pytest.raises(ValidationError, match="поставщиком"):
        create_contract(
            membership=membership,
            actor=user,
            supplier=buyer,
            number="СПЕЦ.0",
            lines=[{"product": world.wheat, "quantity": Decimal("1000"), "price": Decimal("10")}],
            key=uuid4(),
        )
    with pytest.raises(ValidationError, match="строку"):
        create_contract(membership=membership, actor=user, supplier=seller, number="ПУСТО", lines=[], key=uuid4())
    contract = create_contract(
        membership=membership,
        actor=user,
        supplier=seller,
        number="СПЕЦ.1",
        lines=[
            {"product": world.wheat, "quantity": Decimal("1500000"), "price": Decimal("20.5")},
            {"product": world.sack, "quantity": Decimal("100"), "price": Decimal("15")},
        ],
        key=uuid4(),
    )
    create_contract(
        membership=membership,
        actor=user,
        supplier=seller,
        number="СПЕЦ.2",
        lines=[{"product": world.wheat, "quantity": Decimal("1050000"), "price": Decimal("21.5")}],
        key=uuid4(),
    )
    assert SupplyContract.objects.filter(supplier=seller).count() == 2
    wheat_line = contract.lines.get(product=world.wheat)
    ledger = StockLedgerEntry.objects.count()
    debts = SupplierObligation.objects.count()
    waiting = add_shipment(
        membership=membership,
        actor=user,
        line=wheat_line,
        station=station,
        wagon_count=6,
        quantity=Decimal("420000"),
        key=uuid4(),
    )
    arrived = add_shipment(
        membership=membership,
        actor=user,
        line=wheat_line,
        station=station,
        wagon_count=4,
        quantity=Decimal("280000"),
        key=uuid4(),
    )
    assert contract_position(contract)["arrived_sum"] == Decimal("0.00")
    assert contract_position(contract)["due"] == Decimal("0.00")
    receive_at_factory(
        membership=membership,
        actor=user,
        shipment=arrived,
        warehouse=world.raw,
        arrived_on=date(2026, 1, 8),
        key=uuid4(),
    )
    position = contract_position(contract)
    assert position["ordered_sum"] == Decimal("30751500.00")
    assert position["arrived_sum"] == Decimal("5740000.00")
    assert position["due"] == Decimal("5740000.00")
    wheat_row = next(row for row in position["lines"] if row["line"].pk == wheat_line.pk)
    assert wheat_row["remaining_qty"] == Decimal("1220000")
    assert StockLedgerEntry.objects.count() == ledger
    assert SupplierObligation.objects.count() == debts
    add_contract_payment(membership=membership, actor=user, contract=contract, paid_on=date(2026, 1, 18), amount=Decimal("1000000"), key=uuid4())
    assert contract_position(contract)["due"] == Decimal("4740000.00")
    add_shipment(
        membership=membership,
        actor=user,
        line=wheat_line,
        station=station,
        wagon_count=20,
        quantity=Decimal("1400000"),
        key=uuid4(),
    )
    receive_at_factory(
        membership=membership,
        actor=user,
        shipment=waiting,
        warehouse=world.raw,
        arrived_on=date(2026, 1, 24),
        key=uuid4(),
    )

    client = Client()
    client.force_login(user)
    detail = client.get(reverse("contract_detail", args=[contract.pk])).content.decode()
    assert "КОСТАНАЙ" in detail
    assert "08.01.2026" in detail
    assert "Дата отправки" not in detail
    assert "Партия" not in detail
    assert "Поставки" not in detail
    swod = client.get(reverse("contract_swod")).content.decode()
    assert "СПЕЦ.1" in swod and "СПЕЦ.2" in swod
    assert "ФАКТ.ОТПРАВЛЕНО" in swod and "ОПЛАЧЕНО" in swod and "РАЗНИЦА" in swod
    assert "КОСТАНАЙ" in swod
    assert "8 610 000" in swod
    assert "1 000 000" in swod
    assert "42 050 000" in swod
    assert "Дата отправки" not in swod
    payments = client.get(reverse("payment_list")).content.decode()
    assert "13350000.00" in payments
    outsider, outsider_membership = _person("outsider-book", world.company, ["core.view_workspace"], [world.raw])
    client.force_login(outsider)
    assert client.get(reverse("contract_list")).status_code == 403
    with pytest.raises(PermissionDenied):
        create_contract(
            membership=outsider_membership,
            actor=outsider,
            supplier=seller,
            number="ЧУЖОЙ",
            lines=[{"product": world.wheat, "quantity": Decimal("1"), "price": Decimal("1")}],
            key=uuid4(),
        )
