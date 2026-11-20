from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.core.models import Organization, Party
from apps.core.quantities import line_amount, q_money, q_rate
from apps.core.services import record_opening
from apps.finance.models import CashOperation, MoneyAccount, MoneyDocument, OpenItem
from apps.finance.queries import item_remaining, money_balance, party_amount
from apps.finance.services import record_money
from apps.inventory.models import Product, ProductCategory, StockMove, StorageLocation, Warehouse
from apps.inventory.queries import stock_qty
from apps.inventory.services import record_receipt
from apps.procurement.models import RailwayStation, Shipment
from apps.procurement.services import (
    record_contract,
    record_purchase,
    record_shipment,
)
from tests.wheat_workbook import read_mariam_wheat, workbook_path

OPENING = date(2024, 1, 1)


def test_workbook_keeps_the_first_mariam_contract_apart_from_other_companies():
    book = read_mariam_wheat()
    assert "АНТЕРА" in book.supplier
    assert [spec.number for spec in book.specs] == [str(number) for number in range(1, 11)]
    assert {spec.contract_number for spec in book.specs} == {"80"}
    first = book.specs[0]
    assert first.when == date(2024, 10, 30)
    assert first.quantity == Decimal("1500000")
    assert first.price == Decimal("20.5")
    assert first.payments[0].when == date(2025, 2, 18)
    assert first.payments[0].rate == Decimal("0.975")
    assert sum(item.dispatched for item in first.shipments) == Decimal("1470000")
    assert sum(item.amount for item in first.payments) == Decimal("30135000")
    third = book.specs[2]
    assert third.shipments[0].dispatched == Decimal("420000")
    assert third.shipments[0].accepted == Decimal("419828")
    fourth = book.specs[3]
    assert fourth.quantity == Decimal("1050000")
    assert sum(item.dispatched for item in fourth.shipments) == Decimal("1400000")
    split = next(payment for spec in book.specs for payment in spec.payments if payment.bank_amount is not None)
    assert split.bank_amount == Decimal("2977635")
    assert split.when == date(2025, 11, 20)
    assert [(spec.number, amount) for spec, amount in split.parts] == [("6", Decimal("1737572")), ("7", Decimal("1240063"))]
    assert any(payment.rate is None for spec in book.specs for payment in spec.payments)
    assert any("дан-юг" in name.casefold() for name in book.excluded_companies)
    assert book.jalalabad_rows > 10
    assert book.osh_rows > 10
    assert book.later_mariam_specs > 0
    assert book.sunflower_specs > 0
    assert {
        "other-company",
        "jalalabad-sheet",
        "later-mariam-rows",
        "sunflower-section",
        "payment-without-rate",
        "side-costs-not-bank-lines",
        "shipment-without-payment",
    } <= set(book.gaps)
    names = sorted(path.name for path in workbook_path().parent.iterdir() if path.is_file())
    assert names == ["СВОД по пшенице -2025.xlsx"]


@pytest.mark.django_db
def test_mariam_contract_posts_the_workbook_amounts_without_the_other_company():
    book = read_mariam_wheat()
    world = _mill()
    contract = record_contract(
        supplier=world.supplier,
        number="80",
        contract_date=book.specs[0].when,
        description=book.supplier,
    )
    orders = {}
    posted_shipments = []
    station = RailwayStation.objects.create(name="Манас")
    for spec in book.specs:
        order = record_purchase(
            supplier=world.supplier,
            effective_date=spec.when,
            contract=contract,
            specification_number=spec.number,
            currency="RUB",
            lines=[{"product": world.wheat, "quantity": spec.quantity, "price": spec.price}],
        )
        orders[spec.number] = order
        assert order.lines.get().quantity == spec.quantity
        for item in spec.shipments:
            shipment = record_shipment(
                order=order,
                quantity=item.dispatched,
                departure_date=item.when,
                notes=f"{item.station} строка {item.row}",
                departure_station=station,
            )
            posted_shipments.append((spec, item, shipment))
    assert OpenItem.objects.exists() is False
    assert StockMove.objects.exists() is False
    assert posted_shipments[0][2].status == Shipment.Status.DRAFT
    assert StockMove.objects.exists() is False

    for spec, item, shipment in posted_shipments:
        record_receipt(
            supplier=world.supplier,
            warehouse=world.raw,
            effective_date=spec.when,
            lines=[
                {
                    "product": world.wheat,
                    "location": world.wheat_bin,
                    "quantity": item.accepted,
                    "purchase_line": spec_line(orders[spec.number]),
                }
            ],
        )
    assert stock_qty(world.wheat, world.wheat_bin)[0] == sum(
        item.accepted for spec in book.specs for item in spec.shipments
    )

    movements = [payment for spec in book.specs for payment in spec.payments if not payment.absorbed]
    movements.sort(key=lambda payment: (payment.when, payment.row))
    kgs_open = Decimal("0")
    rub_open = Decimal("0")
    for payment in movements:
        if payment.rate is None:
            rub_open += q_money(payment.bank_amount or payment.amount)
        else:
            kgs_open += q_money((payment.bank_amount or payment.amount) * payment.rate)
    record_opening(
        effective_date=OPENING,
        money=[{"account": world.kgs, "amount": kgs_open}, {"account": world.rub, "amount": rub_open}],
    )
    convert = CashOperation.objects.get(code="convert")
    pay = CashOperation.objects.get(code="pay-supplier")
    for payment in movements:
        if payment.rate is not None:
            if payment.bank_amount is not None:
                absorbed = next(item for spec in book.specs for item in spec.payments if item.absorbed)
                assert absorbed.rate == payment.rate
            destination = q_money(payment.bank_amount or payment.amount)
            source = q_money(destination * payment.rate)
            record_money(
                operation=convert,
                account=world.kgs,
                counter_account=world.rub,
                amount=source,
                destination_amount=destination,
                effective_date=payment.when,
                external_reference=f"FX-{payment.row}",
            )
        record_money(
            operation=pay,
            account=world.rub,
            party=world.supplier,
            amount=payment.bank_amount or payment.amount,
            effective_date=payment.when,
            external_reference=f"SVOD-{payment.row}",
            allocations=_allocations(book, orders, payment),
        )
    with pytest.raises(ValidationError):
        record_money(
            operation=convert,
            account=world.kgs,
            counter_account=world.rub,
            amount="1",
            destination_amount="1",
            effective_date=OPENING,
            external_reference="FX-6",
        )

    exchange = MoneyDocument.objects.get(external_reference="FX-6")
    assert exchange.amount == Decimal("3074535.75")
    assert exchange.destination_amount == Decimal("3153370.00")
    assert exchange.rate == q_rate(exchange.amount / exchange.destination_amount)
    debt, advance = _expected_position(book, orders)
    assert party_amount(world.supplier, "payable", "we_owe", "RUB") == debt
    assert party_amount(world.supplier, "payable", "they_owe", "RUB") == advance
    assert money_balance(world.kgs) == 0
    assert money_balance(world.rub) == 0
    assert Party.objects.count() == 1
    side = sum(
        q_money(item.dispatched * item.side_price)
        for spec in book.specs
        for item in spec.shipments
        if item.side_price not in (None, 0)
    )
    accepted_value = sum(
        line_amount(item.accepted, spec_line(orders[spec.number]).price)
        for spec in book.specs
        for item in spec.shipments
    )
    created = OpenItem.objects.filter(
        side=OpenItem.Side.WE_OWE,
        lane=OpenItem.Lane.PAYABLE,
        currency="RUB",
    ).aggregate(total=Sum("amount"))["total"]
    assert side > 0
    assert created == accepted_value


def spec_line(order):
    return order.lines.get()


def _allocations(book, orders, payment):
    if payment.parts:
        pairs = payment.parts
    else:
        owner = next(spec for spec in book.specs if payment in spec.payments)
        pairs = [(owner, payment.amount)]
    plan = []
    for owner, amount in pairs:
        left = _payable_left(orders[owner.number])
        take = min(q_money(amount), left)
        if take > 0:
            plan.append({"order": orders[owner.number], "amount": take})
    return plan or None


def _payable_left(order):
    total = Decimal("0")
    items = OpenItem.objects.filter(
        order=order,
        side=OpenItem.Side.WE_OWE,
        lane=OpenItem.Lane.PAYABLE,
        currency="RUB",
    )
    for item in items:
        total += item_remaining(item)
    return total


def _expected_position(book, orders):
    attributed = {spec.number: Decimal("0") for spec in book.specs}
    for spec in book.specs:
        for payment in spec.payments:
            if payment.absorbed:
                continue
            if payment.parts:
                for owner, amount in payment.parts:
                    attributed[owner.number] += q_money(amount)
            else:
                attributed[spec.number] += q_money(payment.amount)
    debt = Decimal("0")
    advance = Decimal("0")
    for spec in book.specs:
        payable = sum(line_amount(item.accepted, spec_line(orders[spec.number]).price) for item in spec.shipments)
        paid = attributed[spec.number]
        if paid > payable:
            advance += paid - payable
        else:
            debt += payable - paid
    return debt, advance


def _mill():
    Organization.objects.create(legal_name="Мариам-Ош")
    raw = Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    wheat_bin = StorageLocation.objects.create(warehouse=raw, name="Пшеница")
    wheat = Product.objects.create(
        sku="WHEAT", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    supplier = Party.objects.create(name='ООО "АНТЕРА"', is_supplier=True)
    kgs = MoneyAccount.objects.create(name="MBank KGS", kind=MoneyAccount.Kind.BANK, currency="KGS")
    rub = MoneyAccount.objects.create(name="MBank RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    return type("Mill", (), {"raw": raw, "wheat_bin": wheat_bin, "wheat": wheat, "supplier": supplier, "kgs": kgs, "rub": rub})()
