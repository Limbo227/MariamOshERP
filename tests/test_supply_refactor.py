from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models import AuditEntry, Document, Organization, Party
from apps.core.posting import delete_draft_document, unpost_document
from apps.finance.models import CashOperation, ExpenseCategory, MoneyAccount, MoneyMove, OpenItem
from apps.finance.queries import money_balance, party_amount
from apps.finance.reference_data import seed_expense_categories
from apps.finance.services import (
    record_money,
    record_shipment_expense,
    repost_money_document,
    save_expense_category,
    update_draft_money,
)
from apps.inventory.models import ProductCategory, StockMove, Warehouse
from apps.inventory.products import deactivate_category, list_units, save_category, save_product
from apps.inventory.queries import on_hand_weight_kg, stock_by_warehouse, stock_qty
from apps.inventory.services import record_issue
from apps.procurement.models import PurchaseOrder, Shipment, ShipmentWagon
from apps.procurement.reports import (
    shipment_cost,
    specification_progress,
    supplier_balance_report,
    tolerance_warning,
)
from apps.procurement.services import (
    complete_specification,
    declare_wagons,
    delete_shipment,
    post_shipment,
    record_contract,
    record_purchase,
    record_shipment,
    reopen_specification,
    save_delivery_term,
    save_station,
    unpost_shipment,
)
from apps.sales.services import record_sale

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 12)


@pytest.fixture
def mill():
    Organization.objects.create(legal_name="Мариам-Ош")
    raw = Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    finished = Warehouse.objects.create(code="fg", name="Склад готовой продукции", kind=Warehouse.Kind.FINISHED)
    supplier = Party.objects.create(name="Поставщик зерна", is_supplier=True)
    customer = Party.objects.create(name="Покупатель", is_customer=True)
    manas = save_station(name="Манас", country="Кыргызстан")
    sary = save_station(name="Сары-Агач", country="Казахстан")
    cash = MoneyAccount.objects.create(name="Касса KGS", kind=MoneyAccount.Kind.CASH, currency="KGS")
    rub = MoneyAccount.objects.create(name="Банк RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    seed_expense_categories(ExpenseCategory)
    category = ProductCategory.objects.get(code="WHEAT")
    wheat = save_product(sku="WHEAT", name="Пшеница", category=category, unit="KG")
    return {
        "raw": raw,
        "finished": finished,
        "supplier": supplier,
        "customer": customer,
        "manas": manas,
        "sary": sary,
        "cash": cash,
        "rub": rub,
        "wheat": wheat,
    }


def _spec(mill, quantity="1500000", price="20", number="11", tolerance="10"):
    contract = record_contract(
        supplier=mill["supplier"],
        number=f"Д-{number}",
        contract_date=DAY,
        currency="RUB",
        delivery_term=save_delivery_term(name="DAP Манас", code=f"DAP-{number}"),
    )
    order = record_purchase(
        supplier=mill["supplier"],
        effective_date=DAY,
        contract=contract,
        specification_number=number,
        currency="RUB",
        tolerance_percent=tolerance,
        lines=[{"product": mill["wheat"], "quantity": quantity, "price": price}],
    )
    return contract, order


def test_custom_category_and_seeded_units():
    Organization.objects.create(legal_name="Мариам-Ош")
    assert list(list_units().values_list("code", "name")) == [("BAG", "мш"), ("KG", "кг"), ("L", "литр"), ("PCS", "шт")]
    category = save_category(name="Подсолнечное масло", description="Жидкости")
    assert category.active is True
    assert category.role == ProductCategory.Role.OTHER
    oil = save_product(sku="OIL", name="Подсолнечное масло", category=category, unit="L")
    assert oil.unit == "L"
    assert oil.unit_weight_kg is None
    deactivate_category(category)
    category.refresh_from_db()
    assert category.active is False
    with pytest.raises(ValidationError):
        save_product(sku="OIL2", name="Ещё масло", category=category, unit="L")


def test_bag_sale_uses_bag_quantity_and_derives_weight():
    Organization.objects.create(legal_name="Мариам-Ош")
    finished = Warehouse.objects.create(code="fg", name="Склад готовой продукции", kind=Warehouse.Kind.FINISHED)
    flour_category = ProductCategory.objects.get(code="FLOUR")
    sack_category = ProductCategory.objects.get(code="SACK")
    sack = save_product(sku="SACK", name="Пустой мешок", category=sack_category, unit="PCS")
    bars = save_product(
        sku="BARS50",
        name="Барс 50 кг",
        category=flour_category,
        unit="BAG",
        unit_weight_kg="50",
        sack=sack,
    )
    customer = Party.objects.create(name="Покупатель", is_customer=True)
    from apps.inventory.services import ensure_default_location

    location = ensure_default_location(finished)
    from apps.core.services import record_opening

    record_opening(effective_date=DAY, stock=[{"product": bars, "location": location, "quantity": "100"}])
    sale = record_sale(
        customer=customer,
        effective_date=DAY,
        lines=[{"product": bars, "quantity": "100", "price": "1150"}],
    )
    assert sale.lines.get().amount == Decimal("115000.00")
    record_issue(
        customer=customer,
        warehouse=finished,
        effective_date=DAY,
        lines=[{"product": bars, "quantity": "100", "sale_line": sale.lines.get()}],
    )
    assert stock_qty(bars)[0] == Decimal("0")
    assert on_hand_weight_kg(bars) == Decimal("0")
    opening_move = StockMove.objects.get(product=bars, qty_delta__gt=0)
    assert opening_move.unit_code == "BAG"
    assert opening_move.unit_weight_kg == Decimal("50.000")
    assert on_hand_weight_kg(bars, location) == Decimal("0")
    assert opening_move.qty_delta * opening_move.unit_weight_kg == Decimal("5000.000")


def test_warehouse_operation_does_not_ask_for_a_bin(mill):
    before = stock_qty(mill["wheat"])[0]
    contract, order = _spec(mill, quantity="1000", price="20", number="1")
    shipment = record_shipment(
        order=order,
        quantity="1000",
        wagon_count=1,
        departure_station=mill["manas"],
        arrival_date=DAY,
    )
    post_shipment(shipment)
    assert stock_qty(mill["wheat"])[0] == before + Decimal("1000")
    rows = stock_by_warehouse(mill["raw"])
    assert rows[0]["product"] == mill["wheat"]
    assert rows[0]["quantity"] == Decimal("1000")
    assert rows[0]["warehouse"] == mill["raw"]
    assert contract.number == "Д-1"


def test_specification_tolerance_is_informational_and_reopenable(mill):
    _contract, order = _spec(mill, quantity="1500000", price="20", number="11", tolerance="10")
    for weight, percent in (("1200000", Decimal("80.00")), ("1500000", Decimal("100.00")), ("1650000", Decimal("110.00"))):
        shipment = record_shipment(
            order=order,
            quantity=weight,
            wagon_count=1,
            departure_station=mill["manas"],
            arrival_date=DAY,
        )
        post_shipment(shipment)
        progress = specification_progress(order)
        assert progress["received_percent"] == percent
        complete_specification(order)
        order.refresh_from_db()
        assert order.operational_status == PurchaseOrder.OperationalStatus.COMPLETED
        with pytest.raises(ValidationError):
            record_shipment(
                order=order,
                quantity="1",
                departure_station=mill["sary"],
                arrival_date=DAY,
            )
        reopen_specification(order)
        order.refresh_from_db()
        assert order.operational_status == PurchaseOrder.OperationalStatus.IN_PROGRESS
        unpost_shipment(shipment)
    progress = specification_progress(order)
    assert progress["received_quantity"] == Decimal("0")
    assert tolerance_warning(Decimal("1500000"), Decimal("1650000"), Decimal("10")) == "На верхней границе допуска."
    assert "выше" in tolerance_warning(Decimal("1500000"), Decimal("1700000"), Decimal("10"))
    assert "ниже" in tolerance_warning(Decimal("1500000"), Decimal("1200000"), Decimal("10"))


def test_quick_post_then_wagon_details_do_not_repost(mill):
    _contract, order = _spec(mill, quantity="1500000", price="20", number="11")
    shipment = record_shipment(
        order=order,
        quantity="345000",
        wagon_count=5,
        departure_station=mill["manas"],
        departure_date=DAY,
        arrival_date=DAY,
    )
    assert shipment.status == Shipment.Status.DRAFT
    assert StockMove.objects.exists() is False
    assert OpenItem.objects.exists() is False
    posted = post_shipment(shipment)
    assert posted.status == Shipment.Status.POSTED
    assert stock_qty(mill["wheat"])[0] == Decimal("345000")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("6900000.00")
    moves = StockMove.objects.count()
    items = OpenItem.objects.count()
    again = post_shipment(posted)
    assert again.pk == posted.pk
    assert StockMove.objects.count() == moves
    assert OpenItem.objects.count() == items
    declare_wagons(
        posted,
        [
            {"wagon_number": "12345678", "weight_kg": "68000"},
            {"wagon_number": "12345679", "weight_kg": "69000"},
            {"wagon_number": "12345680", "weight_kg": "70000"},
            {"wagon_number": "12345681", "weight_kg": "68000"},
            {"wagon_number": "12345682", "weight_kg": "70000"},
        ],
        complete=True,
    )
    posted.refresh_from_db()
    assert posted.details_complete is True
    assert ShipmentWagon.objects.filter(shipment=posted).count() == 5
    assert StockMove.objects.count() == moves
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("6900000.00")
    with pytest.raises(ValidationError):
        declare_wagons(posted, [{"wagon_number": "", "weight_kg": "1"}])
    with pytest.raises(ValidationError):
        declare_wagons(
            posted,
            [{"wagon_number": "1", "weight_kg": "1"}, {"wagon_number": "2", "weight_kg": "1"}],
            complete=True,
        )


def test_stations_can_differ_and_supplier_is_derived(mill):
    contract, order = _spec(mill, number="11")
    second = record_contract(supplier=mill["supplier"], number="Д-другой", contract_date=DAY, currency="RUB")
    other = record_purchase(
        supplier=mill["supplier"],
        effective_date=DAY,
        contract=second,
        specification_number="12",
        currency="RUB",
        lines=[{"product": mill["wheat"], "quantity": "1000", "price": "20"}],
    )
    first = record_shipment(order=order, quantity="189000", wagon_count=3, departure_station=mill["manas"], arrival_date=DAY)
    second_shipment = record_shipment(
        order=order, quantity="1000", wagon_count=1, departure_station=mill["sary"], arrival_date=DAY
    )
    assert first.order.contract.supplier_id == mill["supplier"].pk
    assert second_shipment.departure_station_id != first.departure_station_id
    posted = post_shipment(first)
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("3780000.00")
    assert stock_qty(mill["wheat"])[0] == Decimal("189000")
    assert posted.receipt.document.effective_date == DAY
    assert other.contract_id != contract.pk
    with pytest.raises(ValidationError):
        record_shipment(order=order, quantity="10", wagon_count=1, arrival_date=DAY, departure_station=None)


def test_unpost_keeps_payment_and_blocks_a_later_issue(mill):
    _contract, order = _spec(mill, quantity="189000", price="20", number="3")
    shipment = record_shipment(
        order=order,
        quantity="189000",
        wagon_count=3,
        departure_station=mill["manas"],
        arrival_date=DAY,
    )
    post_shipment(shipment)
    from apps.core.services import record_opening

    record_opening(effective_date=DAY, money=[{"account": mill["rub"], "amount": "10000000"}])
    payment = record_money(
        operation=CashOperation.objects.get(code="pay-supplier"),
        account=mill["rub"],
        amount="1000000",
        effective_date=DAY,
        party=mill["supplier"],
        fifo=True,
    )
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("2780000.00")
    unpost_shipment(shipment)
    payment.refresh_from_db()
    assert payment.document.state == Document.State.POSTED
    assert MoneyMove.objects.filter(document=payment.document).exists() is True
    assert stock_qty(mill["wheat"])[0] == Decimal("0")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("0")
    assert party_amount(mill["supplier"], "payable", "they_owe", "RUB") == Decimal("1000000.00")
    assert AuditEntry.objects.filter(action=AuditEntry.Action.UNPOSTED).exists()
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.DRAFT
    shipment.quantity = Decimal("180000")
    shipment.save()
    post_shipment(shipment)
    assert stock_qty(mill["wheat"])[0] == Decimal("180000")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("3600000.00")
    record_issue(
        customer=mill["customer"],
        warehouse=mill["raw"],
        effective_date=DAY,
        lines=[{"product": mill["wheat"], "quantity": "180000"}],
    )
    with pytest.raises(ValidationError) as exc:
        unpost_shipment(shipment)
    assert "не хватит" in str(exc.value)
    assert stock_qty(mill["wheat"])[0] == Decimal("0")
    with pytest.raises(ValidationError):
        delete_shipment(shipment)


def test_draft_shipment_can_be_deleted_and_posted_cannot(mill):
    _contract, order = _spec(mill, number="4", quantity="1000")
    shipment = record_shipment(order=order, quantity="1000", departure_station=mill["manas"], wagon_count=1)
    delete_shipment(shipment)
    assert Shipment.objects.exists() is False
    assert AuditEntry.objects.filter(action=AuditEntry.Action.DELETED, target_type="shipment").exists()


def test_shipment_expense_does_not_touch_wheat_or_mix_currencies(mill):
    _contract, order = _spec(mill, number="5", quantity="1000", price="20")
    shipment = record_shipment(
        order=order,
        quantity="1000",
        wagon_count=1,
        departure_station=mill["manas"],
        arrival_date=DAY,
    )
    post_shipment(shipment)
    stock = stock_qty(mill["wheat"])[0]
    payable = party_amount(mill["supplier"], "payable", "we_owe", "RUB")
    from apps.core.services import record_opening

    record_opening(effective_date=DAY, money=[{"account": mill["cash"], "amount": "5000"}])
    rail = ExpenseCategory.objects.get(code="RAIL")
    expense = record_shipment_expense(
        account=mill["cash"],
        amount="1500",
        effective_date=DAY,
        category=rail,
        shipment=shipment,
        party=mill["supplier"],
        note="Провозная плата",
    )
    assert money_balance(mill["cash"]) == Decimal("3500.00")
    assert stock_qty(mill["wheat"])[0] == stock
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == payable
    assert expense.shipment_id == shipment.pk
    assert expense.expense_category_id == rail.pk
    shared = save_expense_category(name="Общий логистический")
    record_opening(effective_date=DAY, money=[{"account": mill["cash"], "amount": "800"}])
    record_shipment_expense(
        account=mill["cash"],
        amount="800",
        effective_date=date(2026, 11, 13),
        category=shared,
        order=order,
    )
    cost = shipment_cost(shipment)
    assert cost["purchase_currency"] == "RUB"
    assert cost["purchase_amount"] == Decimal("20000.00")
    assert cost["valued_in_kgs"] is False
    assert cost["kgs_landed_cost"] is None
    assert {row["currency"] for row in cost["expenses_by_currency"]} == {"KGS"}
    progress = specification_progress(order)
    assert progress["unallocated_expenses"][0]["currency"] == "KGS"
    assert progress["unallocated_expenses"][0]["amount"] == Decimal("800.00")
    report = supplier_balance_report(mill["supplier"])
    assert report["position"]["payable"]["RUB"]["we_owe"] == payable


def test_money_document_unpost_edit_and_repost(mill):
    from apps.core.services import record_opening

    record_opening(effective_date=DAY, money=[{"account": mill["cash"], "amount": "1000"}])
    rent = CashOperation.objects.create(
        code="rent-test",
        name="Аренда",
        effect=CashOperation.Effect.PAY_EXPENSE,
        category=CashOperation.Category.OPERATING,
    )
    money = record_money(operation=rent, account=mill["cash"], amount="100", effective_date=DAY)
    assert money_balance(mill["cash"]) == Decimal("900.00")
    unpost_document(money.document)
    assert money_balance(mill["cash"]) == Decimal("1000.00")
    assert money.document.state == Document.State.DRAFT or Document.objects.get(pk=money.document_id).state == Document.State.DRAFT
    update_draft_money(money, amount="250")
    repost_money_document(money)
    assert money_balance(mill["cash"]) == Decimal("750.00")
    unpost_document(money.document)
    delete_draft_document(money.document)
    assert money_balance(mill["cash"]) == Decimal("1000.00")
    assert MoneyMove.objects.filter(account=mill["cash"], amount_delta=-250).exists() is False


def test_confirmed_accountable_expense_does_not_repost_as_cash(mill):
    from apps.core.services import record_opening
    from apps.finance.services import recognize_accountable

    employee = Party.objects.create(name="Экспедитор", is_employee=True)
    record_opening(effective_date=DAY, money=[{"account": mill["cash"], "amount": "1000"}])
    issued = CashOperation.objects.get(code="accountable-advance")
    customs = CashOperation.objects.get(code="customs")
    advance = record_money(
        operation=issued, account=mill["cash"], amount="400", effective_date=DAY, party=employee
    )
    confirmed = recognize_accountable(
        advance=advance.document.open_items.get(),
        operation=customs,
        amount="150",
        effective_date=DAY,
    )
    assert money_balance(mill["cash"]) == Decimal("600.00")
    unpost_document(confirmed.document)
    assert money_balance(mill["cash"]) == Decimal("600.00")
    assert party_amount(employee, "accountable", "they_owe", "KGS") == Decimal("400.00")
    with pytest.raises(ValidationError) as exc:
        repost_money_document(confirmed)
    assert "подотчёт" in str(exc.value)
    assert money_balance(mill["cash"]) == Decimal("600.00")
    assert MoneyMove.objects.filter(document=confirmed.document).exists() is False
