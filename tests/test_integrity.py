import threading
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.core.models import AuditEntry, Document, Organization, Party
from apps.core.posting import unpost_document
from apps.core.services import record_opening, reverse_document
from apps.finance.models import (
    Allocation,
    CashOperation,
    ExpenseCategory,
    MoneyAccount,
    MoneyMove,
    OpenItem,
)
from apps.finance.queries import money_balance, party_amount
from apps.finance.services import record_money, record_shipment_expense, settle_supplier
from apps.inventory.models import ProductCategory, StockMove, Warehouse
from apps.inventory.products import save_product
from apps.inventory.queries import on_hand_weight_kg, stock_qty
from apps.inventory.services import (
    ensure_default_location,
    record_issue,
    record_receipt,
    repost_issue,
    repost_receipt,
)
from apps.procurement.models import Shipment
from apps.procurement.reports import shipment_cost, shipment_rows, specification_progress
from apps.procurement.services import (
    complete_specification,
    declare_wagons,
    delete_shipment,
    post_shipment,
    record_contract,
    record_purchase,
    record_shipment,
    reopen_specification,
    save_station,
    unpost_shipment,
    update_shipment,
)
from apps.production.services import record_production
from apps.sales.services import record_sale, repost_sale
from apps.ui.figures import order_figures

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 12)


@pytest.fixture
def mill():
    Organization.objects.create(legal_name="Мариам-Ош")
    raw = Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    finished = Warehouse.objects.create(code="fg", name="Склад готовой продукции", kind=Warehouse.Kind.FINISHED)
    finished.category = ProductCategory.objects.get(code="FLOUR")
    finished.save(update_fields=["category"])
    supplier = Party.objects.create(name="Поставщик зерна", is_supplier=True)
    customer = Party.objects.create(name="Покупатель", is_customer=True)
    manas = save_station(name="Манас", country="Кыргызстан")
    cash = MoneyAccount.objects.create(name="Касса KGS", kind=MoneyAccount.Kind.CASH, currency="KGS")
    rub = MoneyAccount.objects.create(name="Банк RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    wheat = save_product(sku="WHEAT", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit="KG")
    return {
        "raw": raw,
        "finished": finished,
        "supplier": supplier,
        "customer": customer,
        "manas": manas,
        "cash": cash,
        "rub": rub,
        "wheat": wheat,
    }


def _order(mill, quantity="10000", price="20", number="1"):
    contract = record_contract(
        supplier=mill["supplier"], number=f"Д-{number}", contract_date=DAY, currency="RUB"
    )
    return record_purchase(
        supplier=mill["supplier"],
        effective_date=DAY,
        contract=contract,
        specification_number=number,
        currency="RUB",
        tolerance_percent="10",
        lines=[{"product": mill["wheat"], "quantity": quantity, "price": price}],
    )


def _manual(mill, order, quantity):
    return record_receipt(
        supplier=mill["supplier"],
        warehouse=mill["raw"],
        effective_date=DAY,
        lines=[{"product": mill["wheat"], "quantity": quantity, "purchase_line": order.lines.get()}],
    )


def _post(mill, order, quantity):
    shipment = record_shipment(
        order=order,
        quantity=quantity,
        wagon_count=1,
        departure_station=mill["manas"],
        arrival_date=DAY,
    )
    return post_shipment(shipment)


def test_posted_shipment_blocks_manual_receipt_until_unpost(mill):
    order = _order(mill, number="1")
    posted = _post(mill, order, "1000")
    with pytest.raises(ValidationError) as exc:
        _manual(mill, order, "500")
    assert "проведением поставки" in str(exc.value)
    assert stock_qty(mill["wheat"])[0] == Decimal("1000")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("20000.00")
    unpost_shipment(posted)
    manual = _manual(mill, order, "500")
    assert stock_qty(mill["wheat"])[0] == Decimal("500")
    assert manual.document.open_items.count() == 1
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("10000.00")


def test_posted_manual_receipt_blocks_shipment_until_unpost(mill):
    order = _order(mill, number="2")
    manual = _manual(mill, order, "450")
    shipment = record_shipment(
        order=order, quantity="300", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY
    )
    with pytest.raises(ValidationError) as exc:
        post_shipment(shipment)
    assert "ручная приёмка" in str(exc.value)
    assert stock_qty(mill["wheat"])[0] == Decimal("450")
    unpost_document(manual.document)
    posted = post_shipment(shipment)
    assert posted.status == Shipment.Status.POSTED
    assert stock_qty(mill["wheat"])[0] == Decimal("300")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("6000.00")


def test_several_shipments_and_several_manual_receipts_stay_valid(mill):
    shipped = _order(mill, quantity="5000", number="3")
    _post(mill, shipped, "1000")
    _post(mill, shipped, "2500")
    assert stock_qty(mill["wheat"])[0] == Decimal("3500")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("70000.00")
    assert OpenItem.objects.filter(order=shipped, side=OpenItem.Side.WE_OWE).count() == 2

    manual_order = _order(mill, quantity="5000", number="4")
    _manual(mill, manual_order, "200")
    _manual(mill, manual_order, "300")
    assert stock_qty(mill["wheat"])[0] == Decimal("4000")
    assert OpenItem.objects.filter(order=manual_order).count() == 2


def test_shipment_posts_once_and_internal_receipt_cannot_be_reversed(mill):
    order = _order(mill, number="5")
    shipment = record_shipment(
        order=order, quantity="1000", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY
    )
    posted = post_shipment(shipment)
    again = post_shipment(posted)
    assert again.receipt_id == posted.receipt_id
    assert StockMove.objects.filter(document=posted.receipt.document).count() == 1
    assert posted.receipt.document.open_items.count() == 1
    with pytest.raises(ValidationError) as reversed_exc:
        reverse_document(posted.receipt.document, effective_date=DAY)
    assert "поставки" in str(reversed_exc.value)
    with pytest.raises(ValidationError) as unpost_exc:
        unpost_document(posted.receipt.document)
    assert "поставки" in str(unpost_exc.value)
    posted.receipt.document.refresh_from_db()
    assert posted.receipt.document.state == Document.State.POSTED
    assert stock_qty(mill["wheat"])[0] == Decimal("1000")


def test_unpost_keeps_payment_and_records_the_released_allocation(mill):
    order = _order(mill, quantity="1000", price="20", number="6")
    posted = _post(mill, order, "1000")
    record_opening(effective_date=DAY, money=[{"account": mill["rub"], "amount": "5000"}])
    payment = record_money(
        operation=CashOperation.objects.get(code="pay-supplier"),
        account=mill["rub"],
        amount="1000",
        effective_date=DAY,
        party=mill["supplier"],
        fifo=True,
    )
    receipt_number = posted.receipt.document.number
    unpost_shipment(posted)
    payment.refresh_from_db()
    assert payment.document.state == Document.State.POSTED
    assert MoneyMove.objects.filter(document=payment.document).exists()
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("0")
    assert party_amount(mill["supplier"], "payable", "they_owe", "RUB") == Decimal("1000.00")
    entry = AuditEntry.objects.get(action=AuditEntry.Action.UNPOSTED, target_type="shipment", target_id=str(posted.pk))
    released = entry.snapshot["allocations"]
    assert released[0]["payment_document"] == payment.document.number
    assert released[0]["debt_document"] == receipt_number
    assert Decimal(released[0]["amount"]) == Decimal("1000.00")
    foreign = AuditEntry.objects.get(action=AuditEntry.Action.UNPOSTED, target_type="allocation")
    assert foreign.snapshot["payment_document"] == payment.document.number
    assert foreign.snapshot["debt_document"] == receipt_number


def test_posting_failure_does_not_leave_a_partial_shipment(mill, monkeypatch):
    order = _order(mill, number="7")
    shipment = record_shipment(
        order=order, quantity="1000", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY
    )

    def boom(*args, **kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr("apps.procurement.services.write_audit", boom)
    with pytest.raises(RuntimeError):
        post_shipment(shipment)
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.DRAFT
    assert shipment.receipt_id is None
    assert stock_qty(mill["wheat"])[0] == Decimal("0")
    assert OpenItem.objects.filter(order=order).count() == 0


def test_audit_keeps_price_after_unpost_edit_and_repost(mill):
    order = _order(mill, quantity="5000", price="20", number="8")
    shipment = record_shipment(
        order=order, quantity="1000", wagon_count=2, departure_station=mill["manas"], arrival_date=DAY
    )
    posted = post_shipment(shipment)
    unpost_shipment(posted)
    original = AuditEntry.objects.get(action=AuditEntry.Action.POSTED, target_type="shipment", target_id=str(shipment.pk))
    assert Decimal(original.snapshot["quantity"]) == Decimal("1000")
    assert Decimal(original.snapshot["price"]) == Decimal("20")
    assert original.snapshot["currency"] == "RUB"
    assert Decimal(original.snapshot["payable"]) == Decimal("20000.00")
    assert original.snapshot["wagon_count"] == 2
    update_shipment(shipment, quantity="900")
    changed = AuditEntry.objects.filter(action=AuditEntry.Action.UPDATED, target_type="shipment").latest("pk")
    assert Decimal(changed.snapshot["previous"]["quantity"]) == Decimal("1000")
    assert Decimal(changed.snapshot["new"]["quantity"]) == Decimal("900")
    post_shipment(shipment)
    history = list(
        AuditEntry.objects.filter(action=AuditEntry.Action.POSTED, target_type="shipment", target_id=str(shipment.pk))
        .order_by("pk")
    )
    assert Decimal(history[0].snapshot["payable"]) == Decimal("20000.00")
    assert Decimal(history[1].snapshot["payable"]) == Decimal("18000.00")
    assert stock_qty(mill["wheat"])[0] == Decimal("900")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("18000.00")


def test_deleted_draft_keeps_an_audit_snapshot(mill):
    order = _order(mill, number="9")
    shipment = record_shipment(
        order=order, quantity="640", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY
    )
    delete_shipment(shipment)
    entry = AuditEntry.objects.get(action=AuditEntry.Action.DELETED, target_type="shipment", target_id=str(shipment.pk))
    assert Decimal(entry.snapshot["quantity"]) == Decimal("640")
    assert entry.snapshot["specification"] == order.document.number
    assert Shipment.objects.filter(pk=shipment.pk).exists() is False


def test_draft_shipments_are_not_received_and_tolerance_does_not_block_completion(mill):
    order = _order(mill, quantity="1500000", number="10")
    record_shipment(order=order, quantity="500000", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY)
    _post(mill, order, "100000")
    progress = specification_progress(order)
    assert progress["received_quantity"] == Decimal("100000")
    assert progress["posted_shipment_count"] == 1
    assert progress["draft_shipment_count"] == 1
    assert progress["ordered_quantity"] == Decimal("1500000")
    figures = order_figures([order.pk])[order.pk]
    assert figures["dispatched_qty"] == Decimal("100000")
    assert figures["draft_qty"] == Decimal("500000")
    assert figures["accepted_qty"] == Decimal("100000")
    row = next(item for item in shipment_rows() if item["shipment"].quantity == Decimal("500000"))
    assert row["purchase_amount"] == Decimal("0.00")
    assert row["draft_weight_kg"] == Decimal("500000")
    assert row["received_weight_kg"] == Decimal("0")
    complete_specification(order)
    order.refresh_from_db()
    assert order.operational_status == order.OperationalStatus.COMPLETED
    reopen_specification(order)
    order.refresh_from_db()
    assert order.operational_status == order.OperationalStatus.IN_PROGRESS


def test_wagon_rules_and_metadata_after_posting(mill):
    order = _order(mill, quantity="10000", number="11")
    incomplete = record_shipment(
        order=order,
        quantity="1000",
        wagon_count=2,
        wagon_number="501",
        departure_station=mill["manas"],
        arrival_date=DAY,
    )
    with pytest.raises(ValidationError):
        post_shipment(incomplete)
    quick = record_shipment(
        order=order, quantity="1000", wagon_count=2, departure_station=mill["manas"], arrival_date=DAY
    )
    posted = post_shipment(quick)
    stock = stock_qty(mill["wheat"])[0]
    payable = party_amount(mill["supplier"], "payable", "we_owe", "RUB")
    declare_wagons(
        posted,
        [{"wagon_number": "11", "weight_kg": "400"}, {"wagon_number": "12", "weight_kg": "600"}],
        complete=True,
    )
    assert stock_qty(mill["wheat"])[0] == stock
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == payable
    with pytest.raises(ValidationError) as exc:
        update_shipment(posted, quantity="900")
    assert "отмените выполнение" in str(exc.value)


def test_bag_flour_production_uses_the_warehouse_and_consumes_sacks_once(mill):
    sack = save_product(sku="SACK", name="Мешок", category=ProductCategory.objects.get(code="SACK"), unit="PCS")
    flour = save_product(
        sku="HV",
        name="Мука высшего сорта",
        category=ProductCategory.objects.get(code="FLOUR"),
        unit="BAG",
        unit_weight_kg="50",
        sack=sack,
    )
    assert flour.unit == "BAG"
    raw_bin = ensure_default_location(mill["raw"])
    record_opening(
        effective_date=DAY,
        stock=[
            {"product": mill["wheat"], "location": raw_bin, "quantity": "5000"},
            {"product": sack, "location": raw_bin, "quantity": "100"},
        ],
    )
    record_production(
        effective_date=DAY,
        outputs=[
            {
                "product": flour,
                "warehouse": mill["finished"],
                "packaging_warehouse": mill["raw"],
                "quantity": "100",
            }
        ],
        inputs=[{"product": mill["wheat"], "warehouse": mill["raw"], "quantity": "4000"}],
    )
    assert stock_qty(flour)[0] == Decimal("100")
    assert stock_qty(flour)[1] is None
    assert on_hand_weight_kg(flour) == Decimal("5000")
    assert stock_qty(sack)[0] == Decimal("0")
    assert stock_qty(mill["wheat"])[0] == Decimal("1000")
    sale = record_sale(
        customer=mill["customer"],
        effective_date=DAY,
        lines=[{"product": flour, "quantity": "100", "price": "1150"}],
    )
    assert sale.document.open_items.get().amount == Decimal("115000.00")


def test_receipt_unpost_is_blocked_when_production_used_the_stock(mill):
    sack = save_product(sku="SACK2", name="Мешок", category=ProductCategory.objects.get(code="SACK"), unit="PCS")
    flour = save_product(
        sku="MUKA",
        name="Мука",
        category=ProductCategory.objects.get(code="FLOUR"),
        unit="KG",
        package_kg="50",
        sack=sack,
    )
    raw_bin = ensure_default_location(mill["raw"])
    record_opening(effective_date=DAY, stock=[{"product": sack, "location": raw_bin, "quantity": "10"}])
    order = _order(mill, quantity="1000", price="10", number="12")
    receipt = _manual(mill, order, "1000")
    record_production(
        effective_date=DAY,
        outputs=[
            {
                "product": flour,
                "warehouse": mill["finished"],
                "packaging_warehouse": mill["raw"],
                "quantity": "500",
                "bags": 10,
            }
        ],
        inputs=[{"product": mill["wheat"], "warehouse": mill["raw"], "quantity": "800"}],
    )
    with pytest.raises(ValidationError) as exc:
        unpost_document(receipt.document)
    assert "не хватит" in str(exc.value)
    assert stock_qty(mill["wheat"])[0] == Decimal("200")
    assert receipt.document.state == Document.State.POSTED


def test_shipment_expense_stays_outside_the_wheat_payable(mill):
    order = _order(mill, quantity="1000", price="20", number="13")
    posted = _post(mill, order, "1000")
    record_opening(effective_date=DAY, money=[{"account": mill["cash"], "amount": "5000"}])
    expense = record_shipment_expense(
        account=mill["cash"],
        amount="1500",
        effective_date=DAY,
        category=ExpenseCategory.objects.get(code="RAIL"),
        shipment=posted,
    )
    drafted = unpost_shipment(posted)
    expense.refresh_from_db()
    assert expense.document.state == Document.State.POSTED
    assert money_balance(mill["cash"]) == Decimal("3500.00")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("0")
    assert stock_qty(mill["wheat"])[0] == Decimal("0")
    assert expense.document.open_items.exists() is False
    draft = record_shipment(
        order=order, quantity="100", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY
    )
    record_shipment_expense(
        account=mill["cash"],
        amount="100",
        effective_date=DAY,
        category=ExpenseCategory.objects.get(code="TRANSPORT"),
        shipment=draft,
    )
    with pytest.raises(ValidationError):
        delete_shipment(draft)
    assert MoneyMove.objects.filter(document__money__shipment=draft).exists()
    cost = shipment_cost(drafted)
    assert cost["purchase_currency"] == "RUB"
    assert cost["kgs_landed_cost"] is None
    assert cost["valued_in_kgs"] is False
    assert {row["currency"] for row in cost["expenses_by_currency"]} == {"KGS"}


def test_opening_and_settlement_are_not_forced_through_generic_repost(mill):
    opening = record_opening(
        effective_date=DAY,
        stock=[{"product": mill["wheat"], "location": ensure_default_location(mill["raw"]), "quantity": "5"}],
    )
    with pytest.raises(ValidationError) as opening_exc:
        unpost_document(opening.document)
    assert "Начальные остатки" in str(opening_exc.value)
    assert stock_qty(mill["wheat"])[0] == Decimal("5")

    order = _order(mill, quantity="1000", price="20", number="14")
    _manual(mill, order, "1000")
    record_opening(effective_date=DAY, money=[{"account": mill["rub"], "amount": "20000"}])
    record_money(
        operation=CashOperation.objects.get(code="pay-supplier"),
        account=mill["rub"],
        amount="20000",
        effective_date=DAY,
        party=mill["supplier"],
        fifo=False,
    )
    settlement = settle_supplier(party=mill["supplier"], effective_date=DAY, fifo=True, currency="RUB")
    assert Allocation.objects.filter(document=settlement).exists()
    with pytest.raises(ValidationError) as settlement_exc:
        unpost_document(settlement)
    assert "Зачёт" in str(settlement_exc.value)
    assert Allocation.objects.filter(document=settlement).exists()
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("0")


def test_currency_conversion_keeps_both_amounts(mill):
    record_opening(
        effective_date=DAY,
        money=[{"account": mill["cash"], "amount": "5000"}, {"account": mill["rub"], "amount": "100"}],
    )
    money = record_money(
        operation=CashOperation.objects.get(code="convert"),
        account=mill["cash"],
        counter_account=mill["rub"],
        amount="1000",
        destination_amount="850",
        effective_date=DAY,
    )
    deltas = set(money.document.money_moves.values_list("amount_delta", flat=True))
    assert Decimal("-1000.00") in deltas
    assert Decimal("850.00") in deltas
    assert money_balance(mill["cash"]) == Decimal("4000.00")
    assert money_balance(mill["rub"]) == Decimal("950.00")
    posted = AuditEntry.objects.get(action=AuditEntry.Action.POSTED, document=money.document)
    assert posted.snapshot["currency"] == "KGS"
    assert posted.snapshot["counter_currency"] == "RUB"
    assert Decimal(posted.snapshot["amount"]) == Decimal("1000.00")
    assert Decimal(posted.snapshot["destination_amount"]) == Decimal("850.00")


def test_sale_and_issue_return_to_draft_and_repost_once(mill):
    sale = record_sale(
        customer=mill["customer"],
        effective_date=DAY,
        lines=[{"product": mill["wheat"], "quantity": "10", "price": "50"}],
    )
    unpost_document(sale.document)
    assert sale.document.open_items.exists() is False
    repost_sale(sale)
    assert sale.document.open_items.get().amount == Decimal("500.00")
    _manual(mill, _order(mill, quantity="10", price="20", number="17"), "10")
    issue = record_issue(
        customer=mill["customer"],
        warehouse=mill["raw"],
        effective_date=DAY,
        lines=[{"product": mill["wheat"], "quantity": "4", "sale_line": sale.lines.get()}],
    )
    unpost_document(issue.document)
    assert stock_qty(mill["wheat"])[0] == Decimal("10")
    repost_issue(issue)
    assert stock_qty(mill["wheat"])[0] == Decimal("6")
    with pytest.raises(ValidationError) as exc:
        unpost_document(sale.document)
    assert "выдач" in str(exc.value)


def test_manual_receipt_can_be_unposted_and_reposted_once(mill):
    order = _order(mill, number="15")
    receipt = _manual(mill, order, "700")
    unpost_document(receipt.document)
    assert stock_qty(mill["wheat"])[0] == Decimal("0")
    repost_receipt(receipt)
    assert stock_qty(mill["wheat"])[0] == Decimal("700")
    assert party_amount(mill["supplier"], "payable", "we_owe", "RUB") == Decimal("14000.00")
    assert receipt.document.open_items.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_receipt_channels_cannot_both_commit(mill):
    order = _order(mill, quantity="10000", number="16")
    shipment = record_shipment(
        order=order, quantity="1000", wagon_count=1, departure_station=mill["manas"], arrival_date=DAY
    )
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def ship():
        try:
            barrier.wait(timeout=15)
            results.append(post_shipment(shipment))
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    def manual():
        try:
            barrier.wait(timeout=15)
            results.append(_manual(mill, order, "2000"))
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=ship), threading.Thread(target=manual)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert len(errors) == 1
    assert "долг" in str(errors[0])
    quantity = stock_qty(mill["wheat"])[0]
    assert quantity in (Decimal("1000"), Decimal("2000"))
    payable = party_amount(mill["supplier"], "payable", "we_owe", "RUB")
    assert payable in (Decimal("20000.00"), Decimal("40000.00"))
    assert OpenItem.objects.filter(order=order, side=OpenItem.Side.WE_OWE).count() == 1
