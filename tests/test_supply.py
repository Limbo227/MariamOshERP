from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Supplier
from apps.core.models import Company
from apps.inventory.models import GoodsReceipt, StockLedgerEntry
from apps.inventory.posting import create_receipt, post_adjustment, post_receipt
from apps.procurement.models import Attachment, CustomsAcceptance, PurchaseCharge, PurchaseOrder
from apps.procurement.services import (
    OrderLineInput,
    accept_at_customs,
    add_wagon,
    confirm_order,
    create_order,
    create_shipment,
)
from apps.quality.models import (
    LocalQualityValue,
    QualityInspection,
    ReleaseDecision,
    SupplierQualityValue,
)
from apps.quality.services import compare_quality, release_quantity
from apps.settlements.models import ObligationEntry, SupplierObligation, SupplierPayment
from apps.settlements.services import (
    add_charge_payment,
    obligation_position,
    record_manual_obligation,
    record_payment,
)
from tests.conftest import _person

pytestmark = pytest.mark.django_db

SUPPLY_PERMS = [
    "core.view_workspace",
    "procurement.view_purchaseorder",
    "procurement.add_purchaseorder",
    "procurement.confirm_purchaseorder",
    "procurement.amend_purchaseorder",
    "procurement.view_purchaseprice",
    "procurement.add_shipment",
    "procurement.add_transportunit",
    "procurement.add_purchasecharge",
    "settlements.add_supplierpayment",
    "inventory.add_goodsreceipt",
    "inventory.view_goodsreceipt",
    "inventory.add_stockadjustment",
    "quality.add_releasedecision",
    "quality.add_supplierqualityvalue",
]


def _supply(world):
    user, membership = _person("supply", world.company, SUPPLY_PERMS, [world.raw, world.finished])
    supplier = Supplier.objects.create(company=world.company, name="ТОО «Синтетика-Зерно»", reference="SYN-GRAIN")
    return user, membership, supplier


def _order(world, membership, user, supplier, quantity="10000", price="20", key=None):
    return create_order(
        membership=membership,
        actor=user,
        supplier=supplier,
        reference="Синтетический заказ",
        effective_date=date(2026, 4, 1),
        lines=[OrderLineInput(product_id=world.wheat.pk, quantity=Decimal(quantity), unit_price=Decimal(price))],
        batch_number="SYN-44",
        wagon_count=4,
        key=key or uuid4(),
    )


def _receive(world, membership, user, supplier, quantity, order=None, when=date(2026, 4, 2)):
    acceptance_id = None
    if order is not None:
        acceptance_id = CustomsAcceptance.objects.create(
            order=order, port="Ош", quantity=Decimal(quantity), accepted_on=when, actor=user
        ).pk
    receipt = create_receipt(
        membership=membership,
        actor=user,
        supplier=supplier,
        warehouse=world.raw,
        reference=f"Приход {quantity}",
        effective_date=when,
        lines=[{
            "product_id": world.wheat.pk,
            "location_id": world.section_a.pk,
            "quantity": Decimal(quantity),
            "basis": world.weighed,
            "order_line_id": order.lines.get().pk if order else None,
            "batch_reference": "SYN-BATCH",
        }],
        order_id=order.pk if order else None,
        customs_acceptance_id=acceptance_id,
        key=uuid4(),
    )
    return post_receipt(membership=membership, actor=user, receipt_id=receipt.pk)


def _stock(world):
    total = StockLedgerEntry.objects.filter(product=world.wheat, location=world.section_a).aggregate(total=Sum("quantity"))["total"]
    return total or Decimal("0")


def test_confirm_creates_debt_once_and_leaves_stock_empty(world):
    user, membership, supplier = _supply(world)
    order = _order(world, membership, user, supplier)
    assert order.state == PurchaseOrder.State.DRAFT
    assert SupplierObligation.objects.count() == 0
    assert _stock(world) == 0

    confirm_order(membership=membership, actor=user, order_id=order.pk)
    confirm_order(membership=membership, actor=user, order_id=order.pk)
    entries = ObligationEntry.objects.filter(obligation__order=order)
    assert entries.count() == 1
    assert entries.get().amount == Decimal("200000.00")
    assert _stock(world) == 0


def test_split_receipt_adds_stock_without_new_debt(world):
    user, membership, supplier = _supply(world)
    order = _order(world, membership, user, supplier)
    confirm_order(membership=membership, actor=user, order_id=order.pk)
    first = _receive(world, membership, user, supplier, "3000", order, date(2026, 4, 2))
    post_receipt(membership=membership, actor=user, receipt_id=first.pk)
    _receive(world, membership, user, supplier, "3000", order, date(2026, 4, 3))
    _receive(world, membership, user, supplier, "4000", order, date(2026, 4, 4))
    assert _stock(world) == Decimal("10000")
    assert ObligationEntry.objects.count() == 1
    assert obligation_position(order.supplierobligation)["due"] == Decimal("200000.00")


def test_short_receipt_amendment_and_payment_keep_the_original_plan(world):
    user, membership, supplier = _supply(world)
    order = _order(world, membership, user, supplier)
    confirm_order(membership=membership, actor=user, order_id=order.pk)
    _receive(world, membership, user, supplier, "9800", order)
    assert _stock(world) == Decimal("9800")
    assert obligation_position(order.supplierobligation)["due"] == Decimal("200000.00")
    assert order.lines.get().quantity == Decimal("10000")

    from apps.procurement.services import amend_order

    amend_order(
        membership=membership,
        actor=user,
        order_id=order.pk,
        reason="Принято меньше",
        effective_date=date(2026, 4, 5),
        terms=[(order.lines.get().pk, Decimal("9800"), Decimal("20"))],
    )
    order.lines.get().refresh_from_db()
    assert order.lines.get().quantity == Decimal("10000")
    assert obligation_position(order.supplierobligation)["due"] == Decimal("196000.00")

    record_payment(
        membership=membership,
        actor=user,
        supplier=supplier,
        amount=Decimal("50000"),
        paid_on=date(2026, 4, 6),
        external_reference="BANK-50",
        method=SupplierPayment.Method.BANK,
        allocations=[{"obligation_id": order.supplierobligation.pk, "amount": Decimal("50000")}],
        key=uuid4(),
    )
    assert obligation_position(order.supplierobligation)["due"] == Decimal("146000.00")


def test_payment_rules_credit_and_customs_charge(world):
    user, membership, supplier = _supply(world)
    first = _order(world, membership, user, supplier, quantity="10", price="10")
    second = _order(world, membership, user, supplier, quantity="10", price="5", key=uuid4())
    confirm_order(membership=membership, actor=user, order_id=first.pk)
    confirm_order(membership=membership, actor=user, order_id=second.pk)
    with pytest.raises(ValidationError):
        record_payment(
            membership=membership,
            actor=user,
            supplier=supplier,
            amount=Decimal("100"),
            paid_on=date(2026, 4, 6),
            external_reference="TOO-MUCH",
            method=SupplierPayment.Method.BANK,
            allocations=[
                {"obligation_id": first.supplierobligation.pk, "amount": Decimal("80")},
                {"obligation_id": second.supplierobligation.pk, "amount": Decimal("30")},
            ],
            key=uuid4(),
        )
    record_payment(
        membership=membership,
        actor=user,
        supplier=supplier,
        amount=Decimal("150"),
        paid_on=date(2026, 4, 6),
        external_reference="SPLIT",
        method=SupplierPayment.Method.BANK,
        allocations=[
            {"obligation_id": first.supplierobligation.pk, "amount": Decimal("100")},
            {"obligation_id": second.supplierobligation.pk, "amount": Decimal("50")},
        ],
        key=uuid4(),
    )
    assert obligation_position(first.supplierobligation)["due"] == 0
    assert obligation_position(second.supplierobligation)["due"] == 0

    paid = _order(world, membership, user, supplier, key=uuid4())
    confirm_order(membership=membership, actor=user, order_id=paid.pk)
    record_payment(
        membership=membership,
        actor=user,
        supplier=supplier,
        amount=Decimal("200000"),
        paid_on=date(2026, 4, 7),
        external_reference="FULL",
        method=SupplierPayment.Method.BANK,
        allocations=[{"obligation_id": paid.supplierobligation.pk, "amount": Decimal("200000")}],
        key=uuid4(),
    )
    from apps.procurement.services import amend_order

    amend_order(
        membership=membership,
        actor=user,
        order_id=paid.pk,
        reason="Ниже уже оплаченного",
        effective_date=date(2026, 4, 8),
        terms=[(paid.lines.get().pk, Decimal("9800"), Decimal("20"))],
    )
    position = obligation_position(paid.supplierobligation)
    assert position["due"] == 0
    assert position["credit"] == Decimal("4000.00")
    assert SupplierPayment.objects.filter(external_reference="FULL").count() == 1

    shipment = create_shipment(membership=membership, actor=user, supplier=supplier, reference="Партия", customs_port="Ош")
    charge = PurchaseCharge.objects.create(shipment=shipment, counterparty="Таможня", amount=Decimal("1000.00"), charged_on=date(2026, 4, 8), note="Сбор")
    before = obligation_position(paid.supplierobligation)
    add_charge_payment(charge_id=charge.pk, method="BANK", amount=Decimal("1000.00"), paid_on=date(2026, 4, 8), reference="CUSTOMS")
    assert obligation_position(paid.supplierobligation) == before


def test_quality_is_optional_and_release_is_manual(world):
    user, membership, supplier = _supply(world)
    order = _order(world, membership, user, supplier, quantity="3000", price="20")
    confirm_order(membership=membership, actor=user, order_id=order.pk)
    receipt = _receive(world, membership, user, supplier, "3000", order)
    assert receipt.state == GoodsReceipt.State.POSTED
    shipment = create_shipment(membership=membership, actor=user, supplier=supplier, reference="Паспорт", customs_port="", order_id=order.pk)
    wagon = add_wagon(membership=membership, shipment_id=shipment.pk, identifier="W-1", declared_quantity=Decimal("3000"))
    SupplierQualityValue.objects.create(shipment=shipment, transport_unit=wagon, parameter="Влажность", number=Decimal("13.5"), unit="%")
    inspection = QualityInspection.objects.create(company=world.company, transport_unit=wagon, inspected_on=date(2026, 4, 3), inspector=user)
    LocalQualityValue.objects.create(inspection=inspection, parameter="Влажность", number=Decimal("14.0"), unit="%")
    compared = compare_quality(shipment=shipment, transport_unit=wagon)
    assert compared == [{"parameter": "Влажность", "unit": "%", "passport": Decimal("13.5"), "local": Decimal("14.0")}]
    assert ReleaseDecision.objects.count() == 0

    other = Company.objects.create(name="Другое", code="other-mill")
    with pytest.raises(ValidationError):
        Attachment.objects.create(company=other, order=order, filename="passport.pdf", storage_key="synthetic", actor=user)

    line = receipt.lines.get()
    key = uuid4()
    release_quantity(membership=membership, actor=user, receipt_line=line, quantity=Decimal("2000"), reason="Допуск", released_on=date(2026, 4, 9), key=key)
    release_quantity(membership=membership, actor=user, receipt_line=line, quantity=Decimal("2000"), reason="Допуск", released_on=date(2026, 4, 9), key=key)
    with pytest.raises(ValidationError):
        release_quantity(membership=membership, actor=user, receipt_line=line, quantity=Decimal("2000"), reason="Ещё", released_on=date(2026, 4, 9), key=uuid4())
    assert line.releases.filter(status=ReleaseDecision.Status.ACTIVE).count() == 1


def test_direct_receipt_does_not_invent_a_debt_and_bad_line_rolls_back(world):
    user, membership, supplier = _supply(world)
    receipt = create_receipt(
        membership=membership,
        actor=user,
        supplier=supplier,
        warehouse=world.raw,
        reference="Мешки без заказа",
        effective_date=date(2026, 4, 2),
        lines=[{"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("12"), "basis": world.basis}],
        key=uuid4(),
    )
    post_receipt(membership=membership, actor=user, receipt_id=receipt.pk)
    assert StockLedgerEntry.objects.filter(product=world.sack).aggregate(total=Sum("quantity"))["total"] == Decimal("12")
    assert SupplierObligation.objects.count() == 0

    with pytest.raises(ValidationError):
        create_receipt(
            membership=membership,
            actor=user,
            supplier=supplier,
            warehouse=world.raw,
            reference="С мукой",
            effective_date=date(2026, 4, 2),
            lines=[
                {"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("1"), "basis": world.basis},
                {"product_id": world.flour.pk, "location_id": world.section_a.pk, "quantity": Decimal("50"), "basis": world.weighed},
            ],
            key=uuid4(),
        )
    assert not GoodsReceipt.objects.filter(reference="С мукой").exists()
    assert StockLedgerEntry.objects.filter(product=world.sack).aggregate(total=Sum("quantity"))["total"] == Decimal("12")


def test_corrections_append_and_reject_a_later_deficit(world):
    user, membership, supplier = _supply(world)
    first_key = uuid4()
    post_adjustment(
        membership=membership,
        actor=user,
        warehouse=world.raw,
        reason="Плюс сто",
        effective_date=date(2026, 3, 1),
        lines=[{"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("100"), "basis": world.basis}],
        key=uuid4(),
    )
    post_adjustment(
        membership=membership,
        actor=user,
        warehouse=world.raw,
        reason="Минус десять",
        effective_date=date(2026, 3, 2),
        lines=[{"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("-10"), "basis": world.basis}],
        key=first_key,
    )
    post_adjustment(
        membership=membership,
        actor=user,
        warehouse=world.raw,
        reason="Минус десять",
        effective_date=date(2026, 3, 2),
        lines=[{"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("-10"), "basis": world.basis}],
        key=first_key,
    )
    assert StockLedgerEntry.objects.filter(product=world.sack).aggregate(total=Sum("quantity"))["total"] == Decimal("90")
    with pytest.raises(ValidationError):
        post_adjustment(
            membership=membership,
            actor=user,
            warehouse=world.raw,
            reason="Списать исходные сто",
            effective_date=date(2026, 3, 3),
            lines=[{"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("-100"), "basis": world.basis}],
            key=uuid4(),
        )
    post_adjustment(
        membership=membership,
        actor=user,
        warehouse=world.raw,
        reason="Списать остаток девяносто",
        effective_date=date(2026, 3, 3),
        lines=[{"product_id": world.sack.pk, "location_id": world.packaging.pk, "quantity": Decimal("-90"), "basis": world.basis}],
        key=uuid4(),
    )
    assert StockLedgerEntry.objects.filter(product=world.sack).aggregate(total=Sum("quantity"))["total"] == Decimal("0")

    post_adjustment(
        membership=membership,
        actor=user,
        warehouse=world.raw,
        reason="Сто первого января",
        effective_date=date(2026, 5, 1),
        lines=[{"product_id": world.wheat.pk, "location_id": world.section_a.pk, "quantity": Decimal("100"), "basis": world.weighed}],
        key=uuid4(),
    )
    post_adjustment(
        membership=membership,
        actor=user,
        warehouse=world.raw,
        reason="Пятьдесят десятого мая",
        effective_date=date(2026, 5, 10),
        lines=[{"product_id": world.wheat.pk, "location_id": world.section_a.pk, "quantity": Decimal("50"), "basis": world.weighed}],
        key=uuid4(),
    )
    with pytest.raises(ValidationError, match="отрицательный остаток"):
        post_adjustment(
            membership=membership,
            actor=user,
            warehouse=world.raw,
            reason="Задним числом",
            effective_date=date(2026, 5, 5),
            lines=[{"product_id": world.wheat.pk, "location_id": world.section_a.pk, "quantity": Decimal("-120"), "basis": world.weighed}],
            key=uuid4(),
        )
    assert _stock(world) == Decimal("150")


def test_storage_and_customs_pages_hide_prices(world):
    user, membership, supplier = _supply(world)
    order = _order(world, membership, user, supplier)
    confirm_order(membership=membership, actor=user, order_id=order.pk)
    storage, _membership = _person(
        "storage-price",
        world.company,
        ["core.view_workspace", "procurement.view_purchaseorder"],
        [world.raw],
    )
    customs, _membership = _person(
        "customs-price",
        world.company,
        ["core.view_workspace", "procurement.view_purchaseorder"],
        [world.raw],
    )
    client = Client()
    client.force_login(storage)
    hidden = client.get(reverse("order_detail", args=[order.pk]))
    assert hidden.status_code == 200
    assert "200000" not in hidden.content.decode()
    assert "20.00" not in hidden.content.decode()
    client.force_login(user)
    visible = client.get(reverse("order_detail", args=[order.pk]))
    text = visible.content.decode()
    assert "200000" in text
    assert "20.00" in text
    client.force_login(customs)
    customs_page = client.get(reverse("order_detail", args=[order.pk]))
    assert "200000" not in customs_page.content.decode()
    assert "20.00" not in customs_page.content.decode()


def test_manual_obligation_is_explicit(world):
    user, membership, supplier = _supply(world)
    record_manual_obligation(
        membership=membership,
        actor=user,
        supplier=supplier,
        amount=Decimal("15"),
        reference="Отдельное основание",
        effective_date=date(2026, 4, 1),
    )
    obligation = SupplierObligation.objects.get(manual_reference="Отдельное основание")
    assert obligation.order_id is None
    assert obligation_position(obligation)["due"] == Decimal("15.00")
    assert PurchaseOrder.objects.count() == 0


def test_each_role_moves_only_its_step(world):
    user, membership, supplier = _supply(world)
    with pytest.raises(ValidationError, match="партия"):
        create_order(
            membership=membership,
            actor=user,
            supplier=supplier,
            reference="Без партии",
            effective_date=date(2026, 4, 1),
            lines=[OrderLineInput(product_id=world.wheat.pk, quantity=Decimal("1000"), unit_price=Decimal("10"))],
        )
    order = _order(world, membership, user, supplier, quantity="1000", price="10")
    assert order.journey() == "Заявка"
    customs_user, customs_membership = _person(
        "customs-flow",
        world.company,
        ["core.view_workspace", "procurement.view_purchaseorder", "procurement.add_customsacceptance"],
        [world.raw],
    )
    with pytest.raises(ValidationError, match="отправленный"):
        accept_at_customs(
            membership=customs_membership,
            actor=customs_user,
            order_id=order.pk,
            port="Карасуу",
            quantity=Decimal("1000"),
            accepted_on=date(2026, 4, 2),
        )
    confirm_order(membership=membership, actor=user, order_id=order.pk)
    order.refresh_from_db()
    assert order.journey() == "Отправлено"
    with pytest.raises(ValidationError, match="таможня"):
        create_receipt(
            membership=membership,
            actor=user,
            supplier=supplier,
            warehouse=world.raw,
            reference="Рано",
            effective_date=date(2026, 4, 3),
            lines=[{"product_id": world.wheat.pk, "location_id": world.section_a.pk, "quantity": Decimal("1000"), "basis": world.weighed, "order_line_id": order.lines.get().pk}],
            order_id=order.pk,
            key=uuid4(),
        )
    accept_at_customs(
        membership=customs_membership,
        actor=customs_user,
        order_id=order.pk,
        port="Карасуу",
        quantity=Decimal("1000"),
        accepted_on=date(2026, 4, 2),
    )
    order.refresh_from_db()
    assert order.journey() == "Прибыло в таможню"
    assert _stock(world) == 0
    assert obligation_position(order.supplierobligation)["due"] == Decimal("10000.00")
    _receive(world, membership, user, supplier, "1000", order)
    order.refresh_from_db()
    assert order.journey() == "На складе"
    assert _stock(world) == Decimal("1000")
    client = Client()
    client.force_login(customs_user)
    table = client.get(reverse("order_list")).content.decode()
    assert "На складе" in table
    assert "SYN-44" in table
    assert "20.00" not in table
    assert "10000.00" not in table
