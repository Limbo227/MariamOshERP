from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from apps.core.models import Document, Organization, Party
from apps.core.quantities import display_rate, q_money, q_rate
from apps.core.services import record_opening, reverse_document
from apps.finance.models import CashOperation, MoneyAccount, MoneyMove, OpenItem
from apps.finance.queries import money_balance, party_amount
from apps.finance.services import recognize_accountable, record_money
from apps.inventory.models import Product, StockMove
from apps.inventory.queries import stock_qty
from apps.inventory.services import record_issue, record_receipt
from apps.procurement.models import RailwayStation, Shipment
from apps.procurement.services import record_contract, record_purchase, record_shipment
from apps.production.queries import wheat_not_entered
from apps.production.services import record_production
from apps.sales.services import record_sale

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 1)


@pytest.fixture
def mill(db):
    from apps.core.models import Party
    from apps.finance.models import MoneyAccount
    from apps.inventory.models import ProductCategory, StorageLocation, Warehouse

    Organization.objects.create(legal_name="Мариам-Ош")
    raw = Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    finished = Warehouse.objects.create(code="fg", name="Склад готовой продукции", kind=Warehouse.Kind.FINISHED)
    finished.category = ProductCategory.objects.get(code="FLOUR")
    finished.save(update_fields=["category"])
    wheat_bin = StorageLocation.objects.create(warehouse=raw, name="Пшеница")
    sack_bin = StorageLocation.objects.create(warehouse=raw, name="Мешки")
    flour_bin = StorageLocation.objects.create(warehouse=finished, name="Мука")
    wheat = Product.objects.create(
        sku="WHEAT", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    sack = Product.objects.create(
        sku="SACK", name="Мешок", category=ProductCategory.objects.get(code="SACK"), unit=Product.Unit.PCS
    )
    flour = Product.objects.create(
        sku="FLOUR",
        name="Мука",
        category=ProductCategory.objects.get(code="FLOUR"),
        unit=Product.Unit.KG,
        package_kg=Decimal("50"),
        sack=sack,
    )
    supplier = Party.objects.create(name="Поставщик зерна", is_supplier=True)
    station = RailwayStation.objects.create(name="Манас")
    customer = Party.objects.create(name="Покупатель", is_customer=True)
    both = Party.objects.create(name="Общий контрагент", is_supplier=True, is_customer=True)
    cash = MoneyAccount.objects.create(name="Касса", kind=MoneyAccount.Kind.CASH)
    bank = MoneyAccount.objects.create(name="Банк", kind=MoneyAccount.Kind.BANK)
    return SimpleNamespace(
        raw=raw,
        finished=finished,
        wheat_bin=wheat_bin,
        sack_bin=sack_bin,
        flour_bin=flour_bin,
        wheat=wheat,
        sack=sack,
        flour=flour,
        supplier=supplier,
        station=station,
        customer=customer,
        both=both,
        cash=cash,
        bank=bank,
        pay=CashOperation.objects.get(code="pay-supplier"),
        receive=CashOperation.objects.get(code="receive-customer"),
        deposit=CashOperation.objects.get(code="deposit-to-bank"),
        electricity=CashOperation.objects.get(code="electricity"),
        tax=CashOperation.objects.get(code="tax"),
    )


def _open_money(mill, account, amount):
    record_opening(effective_date=DAY, money=[{"account": account, "amount": amount}])


def _open_stock(mill, product, location, quantity, bags=None):
    record_opening(
        effective_date=DAY,
        stock=[{"product": product, "location": location, "quantity": quantity, "bags": bags}],
    )


def test_only_one_organization(mill):
    with pytest.raises(ValidationError):
        Organization.objects.create(legal_name="Вторая")


def test_starter_operations_are_a_catalog(mill):
    assert mill.electricity.effect == CashOperation.Effect.PAY_EXPENSE
    assert mill.deposit.effect == CashOperation.Effect.TRANSFER
    assert mill.deposit.source_kind == "CASH"
    assert mill.deposit.destination_kind == "BANK"
    rent = CashOperation.objects.create(
        code="rent",
        name="Аренда",
        effect=CashOperation.Effect.PAY_EXPENSE,
        category=CashOperation.Category.OPERATING,
    )
    _open_money(mill, mill.cash, "1000")
    record_money(operation=rent, account=mill.cash, amount="150", effective_date=DAY)
    assert money_balance(mill.cash) == Decimal("850")
    assert OpenItem.objects.count() == 0


def _accept(mill, order, quantity, **kwargs):
    return record_receipt(
        supplier=order.supplier,
        warehouse=mill.raw,
        effective_date=DAY,
        lines=[
            {
                "product": order.lines.get().product,
                "location": mill.wheat_bin,
                "quantity": quantity,
                "purchase_line": order.lines.get(),
            }
        ],
        **kwargs,
    )


def test_payable_follows_accepted_quantity(mill):
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10000", "price": "20"}],
    )
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    assert stock_qty(mill.wheat)[0] == 0
    _accept(mill, order, "3000")
    _accept(mill, order, "3000")
    _accept(mill, order, "3800")
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("9800")
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == Decimal("196000")
    assert order.document.open_items.exists() is False
    assert OpenItem.objects.filter(order=order).count() == 3
    _accept(mill, order, "201")
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("10001")
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == Decimal("200020")
    assert order.lines.get().quantity == Decimal("10000.000")


def test_accepted_weight_may_be_under_or_over_the_specification(mill):
    short = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "68000", "price": "20"}],
        currency="RUB",
    )
    shipment = record_shipment(
        order=short, quantity="68000", departure_date=DAY, wagon_number="125", departure_station=mill.station
    )
    short_receipt = _accept(mill, short, "67500")
    assert short.lines.get().quantity == Decimal("68000.000")
    assert short_receipt.lines.get().quantity == Decimal("67500.000")
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("67500")
    assert short_receipt.document.open_items.get().amount == Decimal("1350000.00")
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.DRAFT

    heavy = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "68000", "price": "20"}],
        currency="RUB",
    )
    heavy_receipt = _accept(mill, heavy, "70000")
    assert heavy.lines.get().quantity == Decimal("68000.000")
    assert heavy_receipt.lines.get().quantity == Decimal("70000.000")
    assert heavy_receipt.document.open_items.get().order_id == heavy.pk
    assert heavy_receipt.document.open_items.get().amount == Decimal("1400000.00")
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("137500")
    assert party_amount(mill.supplier, "payable", "we_owe", "RUB") == Decimal("2750000.00")


def test_failed_receipt_leaves_stock_and_payable_untouched(mill):
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    with pytest.raises(ValidationError):
        record_receipt(
            supplier=mill.supplier,
            warehouse=mill.raw,
            effective_date=DAY,
            lines=[
                {
                    "product": mill.wheat,
                    "location": mill.wheat_bin,
                    "quantity": "4",
                    "purchase_line": order.lines.get(),
                },
                {
                    "product": mill.wheat,
                    "location": mill.flour_bin,
                    "quantity": "1",
                    "purchase_line": order.lines.get(),
                },
            ],
        )
    assert stock_qty(mill.wheat)[0] == 0
    assert OpenItem.objects.exists() is False
    assert Document.objects.filter(kind=Document.Kind.RECEIPT).exists() is False


def test_supplier_payment_closes_debt_and_leaves_advance(mill):
    _open_money(mill, mill.cash, "250")
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    _accept(mill, order, "10")
    record_money(operation=mill.pay, account=mill.cash, amount="250", effective_date=DAY, party=mill.supplier, fifo=True)
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    assert party_amount(mill.supplier, "payable", "they_owe", "KGS") == Decimal("50")
    assert party_amount(mill.supplier, "receivable", "we_owe", "KGS") == 0
    assert money_balance(mill.cash) == 0


def test_expense_and_tax_do_not_create_debt(mill):
    _open_money(mill, mill.bank, "5000")
    record_money(operation=mill.electricity, account=mill.bank, amount="800", effective_date=DAY)
    record_money(operation=mill.tax, account=mill.bank, amount="200", effective_date=DAY)
    assert money_balance(mill.bank) == Decimal("4000")
    assert OpenItem.objects.count() == 0


def test_cash_deposit_moves_money_without_income(mill):
    _open_money(mill, mill.cash, "100000")
    record_money(
        operation=mill.deposit,
        account=mill.cash,
        counter_account=mill.bank,
        amount="100000",
        effective_date=DAY,
    )
    assert money_balance(mill.cash) == 0
    assert money_balance(mill.bank) == Decimal("100000")
    assert OpenItem.objects.count() == 0
    with pytest.raises(ValidationError):
        record_money(
            operation=mill.deposit,
            account=mill.bank,
            counter_account=mill.cash,
            amount="1",
            effective_date=DAY,
        )


def test_sale_debt_stays_until_paid_and_stock_moves_on_issue(mill):
    _open_stock(mill, mill.flour, mill.flour_bin, "5000", bags=100)
    sale = record_sale(
        customer=mill.customer,
        effective_date=DAY,
        lines=[{"product": mill.flour, "quantity": "5000", "price": "2", "bags": 100}],
    )
    line = sale.lines.get()
    record_issue(
        customer=mill.customer,
        warehouse=mill.finished,
        effective_date=DAY,
        lines=[{"product": mill.flour, "location": mill.flour_bin, "quantity": "3000", "bags": 60, "sale_line": line}],
    )
    quantity, bags = stock_qty(mill.flour, mill.flour_bin)
    assert quantity == Decimal("2000")
    assert bags == 40
    assert party_amount(mill.customer, "receivable", "they_owe", "KGS") == Decimal("10000")
    record_money(operation=mill.receive, account=mill.cash, amount="3000", effective_date=DAY, party=mill.customer)
    assert party_amount(mill.customer, "receivable", "they_owe", "KGS") == Decimal("7000")
    assert money_balance(mill.cash) == Decimal("3000")


def test_one_party_keeps_supplier_and_customer_debts_apart(mill):
    order = record_purchase(
        supplier=mill.both,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "5", "price": "20"}],
    )
    _accept(mill, order, "5")
    record_sale(
        customer=mill.both,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "2", "price": "20"}],
    )
    assert party_amount(mill.both, "payable", "we_owe", "KGS") == Decimal("100")
    assert party_amount(mill.both, "receivable", "they_owe", "KGS") == Decimal("40")


def test_production_posts_quantities_and_leaves_cost_out(mill):
    _open_stock(mill, mill.sack, mill.sack_bin, "100")
    _open_stock(mill, mill.wheat, mill.wheat_bin, "1000")
    report = record_production(
        effective_date=DAY,
        outputs=[
            {
                "product": mill.flour,
                "location": mill.flour_bin,
                "packaging_location": mill.sack_bin,
                "quantity": "5000",
                "bags": 100,
            }
        ],
        inputs=[{"product": mill.wheat, "location": mill.wheat_bin, "quantity": "800"}],
    )
    flour_qty, flour_bags = stock_qty(mill.flour, mill.flour_bin)
    assert flour_qty == Decimal("5000")
    assert flour_bags == 100
    assert stock_qty(mill.sack, mill.sack_bin)[0] == 0
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("200")
    assert wheat_not_entered(report) is False
    assert MoneyMove.objects.filter(document=report.document).count() == 0
    assert "cost" not in {field.name for field in StockMove._meta.fields}
    assert "value" not in {field.name for field in StockMove._meta.fields}


def test_missing_wheat_is_not_stored_as_zero(mill):
    _open_stock(mill, mill.sack, mill.sack_bin, "10")
    report = record_production(
        effective_date=DAY,
        outputs=[
            {
                "product": mill.flour,
                "location": mill.flour_bin,
                "packaging_location": mill.sack_bin,
                "quantity": "500",
                "bags": 10,
            }
        ],
    )
    assert wheat_not_entered(report) is True
    assert stock_qty(mill.wheat)[0] == 0
    assert report.inputs.count() == 0


def test_negative_stock_is_rejected(mill):
    with pytest.raises(ValidationError):
        record_production(
            effective_date=DAY,
            outputs=[
                {
                    "product": mill.flour,
                    "location": mill.flour_bin,
                    "packaging_location": mill.sack_bin,
                    "quantity": "50",
                    "bags": 1,
                }
            ],
        )


def test_posted_facts_are_frozen(mill):
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "1", "price": "10"}],
    )
    order.document.note = "правка"
    with pytest.raises(ValidationError):
        order.document.save()
    receipt = _accept(mill, order, "1")
    move = receipt.document.stock_moves.get()
    move.qty_delta = Decimal("2")
    with pytest.raises(ValidationError):
        move.save()
    item = receipt.document.open_items.get()
    assert item.order_id == order.pk
    item.amount = Decimal("1")
    with pytest.raises(ValidationError):
        item.save()


def test_reverse_receipt_clears_stock_and_payable(mill):
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "4", "price": "25"}],
    )
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    reverse_document(order.document, effective_date=DAY)
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "4", "price": "25"}],
    )
    receipt = _accept(mill, order, "4")
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("4")
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == Decimal("100")
    reverse_document(receipt.document, effective_date=DAY)
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == 0
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    with pytest.raises(ValidationError):
        reverse_document(receipt.document, effective_date=DAY)
    again = _accept(mill, order, "4")
    assert again.document.open_items.get().amount == Decimal("100.00")
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("4")


def test_reverse_payment_reopens_debt_and_cash(mill):
    _open_money(mill, mill.cash, "250")
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    _accept(mill, order, "10")
    payment = record_money(
        operation=mill.pay, account=mill.cash, amount="250", effective_date=DAY, party=mill.supplier, fifo=True
    )
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    reverse_document(payment.document, effective_date=DAY)
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == Decimal("200")
    assert party_amount(mill.supplier, "payable", "they_owe", "KGS") == 0
    assert money_balance(mill.cash) == Decimal("250")


def test_receipt_blocks_purchase_reversal(mill):
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    record_receipt(
        supplier=mill.supplier,
        warehouse=mill.raw,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "location": mill.wheat_bin, "quantity": "10", "purchase_line": order.lines.get()}],
    )
    with pytest.raises(ValidationError):
        reverse_document(order.document, effective_date=DAY)


def test_used_operation_keeps_its_effect(mill):
    _open_money(mill, mill.cash, "10")
    record_money(operation=mill.electricity, account=mill.cash, amount="10", effective_date=DAY)
    mill.electricity.effect = CashOperation.Effect.TRANSFER
    with pytest.raises(ValidationError):
        mill.electricity.save()
    assert Document.objects.filter(kind=Document.Kind.MONEY).count() == 1


def test_supplier_payment_closes_the_oldest_receipt_and_keeps_the_rest_as_advance(mill):
    _open_money(mill, mill.bank, "250")
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    _accept(mill, order, "10")
    stock = StockMove.objects.count()
    record_money(operation=mill.pay, account=mill.bank, amount="250", effective_date=DAY, party=mill.supplier)
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == 0
    assert party_amount(mill.supplier, "payable", "they_owe", "KGS") == Decimal("50")
    assert money_balance(mill.bank) == 0
    assert StockMove.objects.count() == stock


def test_one_payment_splits_across_specifications(mill):
    contract = record_contract(supplier=mill.supplier, number="З-2026", contract_date=DAY)
    spec_8 = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        contract=contract,
        specification_number="8",
        currency="RUB",
        lines=[{"product": mill.wheat, "quantity": "50000", "price": "20"}],
    )
    spec_10 = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        contract=contract,
        specification_number="10",
        currency="RUB",
        lines=[{"product": mill.wheat, "quantity": "25000", "price": "20"}],
    )
    _accept(mill, spec_8, "50000")
    _accept(mill, spec_10, "25000")
    rub_bank = MoneyAccount.objects.create(name="MBank RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    _open_money(mill, rub_bank, "1500000")
    stock = StockMove.objects.count()
    record_money(
        operation=mill.pay,
        account=rub_bank,
        amount="1500000",
        effective_date=DAY,
        party=mill.supplier,
        allocations=[
            {"order": spec_8, "amount": "1000000"},
            {"order": spec_10, "amount": "500000"},
        ],
    )
    assert party_amount(mill.supplier, "payable", "we_owe", "RUB") == 0
    assert party_amount(mill.supplier, "payable", "they_owe", "RUB") == 0
    assert money_balance(rub_bank) == 0
    assert StockMove.objects.count() == stock


def test_advance_is_settled_after_the_goods_arrive(mill):
    rub_bank = MoneyAccount.objects.create(name="MBank RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    _open_money(mill, rub_bank, "5000000")
    record_money(operation=mill.pay, account=rub_bank, amount="5000000", effective_date=DAY, party=mill.supplier)
    assert party_amount(mill.supplier, "payable", "they_owe", "RUB") == Decimal("5000000")
    assert party_amount(mill.supplier, "payable", "we_owe", "RUB") == 0
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "68000", "price": "20"}],
        currency="RUB",
    )
    _accept(mill, order, "67500")
    assert party_amount(mill.supplier, "payable", "we_owe", "RUB") == 0
    assert party_amount(mill.supplier, "payable", "they_owe", "RUB") == Decimal("3650000")
    assert money_balance(rub_bank) == 0
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == Decimal("67500")


def test_allocation_does_not_exceed_the_open_amounts(mill):
    other = record_purchase(
        supplier=mill.both,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    _accept(mill, other, "10")
    order = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
        currency="KGS",
    )
    _accept(mill, order, "10")
    rub = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
        currency="RUB",
    )
    _accept(mill, rub, "10")
    _open_money(mill, mill.bank, "1000")
    with pytest.raises(ValidationError):
        record_money(
            operation=mill.pay,
            account=mill.bank,
            amount="1000",
            effective_date=DAY,
            party=mill.supplier,
            allocations=[{"order": order, "amount": "500"}, {"order": rub, "amount": "100"}],
        )
    with pytest.raises(ValidationError):
        record_money(
            operation=mill.pay,
            account=mill.bank,
            amount="1000",
            effective_date=DAY,
            party=mill.supplier,
            allocations=[{"order": other, "amount": "100"}],
        )
    with pytest.raises(ValidationError):
        record_money(
            operation=mill.pay,
            account=mill.bank,
            amount="1000",
            effective_date=DAY,
            party=mill.supplier,
            allocations=[{"order": order, "amount": "500"}],
        )
    assert money_balance(mill.bank) == Decimal("1000")
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == Decimal("200")
    assert party_amount(mill.supplier, "payable", "we_owe", "RUB") == Decimal("200")


def test_conversion_moves_two_amounts_and_is_not_income(mill):
    rub_bank = MoneyAccount.objects.create(name="MBank RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    convert = CashOperation.objects.get(code="convert")
    commission = CashOperation.objects.get(code="bank-commission")
    _open_money(mill, mill.bank, "1096000")
    conversion = record_money(
        operation=convert,
        account=mill.bank,
        counter_account=rub_bank,
        amount="1095000",
        destination_amount="1000000",
        effective_date=DAY,
        external_reference="STMT-18",
    )
    record_money(operation=commission, account=mill.bank, amount="500", effective_date=DAY, external_reference="STMT-19")
    assert conversion.amount == Decimal("1095000.00")
    assert conversion.destination_amount == Decimal("1000000.00")
    assert conversion.rate == q_rate(Decimal("1095000.00") / Decimal("1000000.00"))
    assert conversion.rate_display() == display_rate(conversion.rate)
    assert money_balance(mill.bank) == Decimal("500")
    assert money_balance(rub_bank) == Decimal("1000000")
    assert OpenItem.objects.exists() is False
    with pytest.raises(ValidationError):
        record_money(
            operation=convert,
            account=mill.bank,
            counter_account=rub_bank,
            amount="1095",
            destination_amount="1000",
            effective_date=DAY,
            external_reference="STMT-18",
        )
    with pytest.raises(ValidationError):
        record_money(
            operation=mill.deposit,
            account=mill.cash,
            counter_account=rub_bank,
            amount="10",
            effective_date=DAY,
        )


def test_conversion_keeps_uneven_statement_amounts(mill):
    rub_bank = MoneyAccount.objects.create(name="MBank RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    convert = CashOperation.objects.get(code="convert")
    source = Decimal("2500000.37")
    destination = Decimal("1847293.19")
    _open_money(mill, mill.bank, source)
    conversion = record_money(
        operation=convert,
        account=mill.bank,
        counter_account=rub_bank,
        amount=source,
        destination_amount=destination,
        rate="99",
        effective_date=DAY,
    )
    assert conversion.amount == source
    assert conversion.destination_amount == destination
    assert conversion.rate == q_rate(source / destination)
    assert conversion.rate != Decimal("99")
    assert conversion.rate_display() == display_rate(conversion.rate)
    assert money_balance(mill.bank) == 0
    assert money_balance(rub_bank) == destination
    assert OpenItem.objects.exists() is False
    with pytest.raises(ValidationError):
        record_money(
            operation=convert,
            account=mill.bank,
            counter_account=rub_bank,
            amount="10",
            destination_amount="0",
            effective_date=DAY,
        )


def test_conversion_keeps_large_statement_amounts(mill):
    rub_bank = MoneyAccount.objects.create(name="MBank RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    convert = CashOperation.objects.get(code="convert")
    source = Decimal("12345678901234.57")
    destination = Decimal("9876543210987.65")
    _open_money(mill, mill.bank, source)
    conversion = record_money(
        operation=convert,
        account=mill.bank,
        counter_account=rub_bank,
        amount=source,
        destination_amount=destination,
        effective_date=DAY,
    )
    assert conversion.amount == source
    assert conversion.destination_amount == destination
    assert conversion.rate == q_rate(source / destination)
    assert q_money(destination * conversion.rate) != source
    assert money_balance(mill.bank) == 0
    assert money_balance(rub_bank) == destination


def test_bank_withdrawal_is_a_transfer_and_rejects_a_duplicate(mill):
    withdraw = CashOperation.objects.get(code="withdraw-from-bank")
    _open_money(mill, mill.bank, "1000")
    record_money(
        operation=withdraw,
        account=mill.bank,
        counter_account=mill.cash,
        amount="400",
        effective_date=DAY,
        external_reference="CASH-1",
    )
    assert money_balance(mill.bank) == Decimal("600")
    assert money_balance(mill.cash) == Decimal("400")
    assert OpenItem.objects.exists() is False
    with pytest.raises(ValidationError):
        record_money(
            operation=withdraw,
            account=mill.bank,
            counter_account=mill.cash,
            amount="10",
            effective_date=DAY,
            external_reference="CASH-1",
        )


def test_customs_expense_follows_the_wagon_and_not_the_wheat_debt(mill):
    contract = record_contract(supplier=mill.supplier, number="З-2026", contract_date=DAY)
    spec = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        contract=contract,
        specification_number="10",
        currency="RUB",
        lines=[{"product": mill.wheat, "quantity": "68000", "price": "20"}],
    )
    _accept(mill, spec, "67500")
    shipment = record_shipment(
        order=spec, quantity="68000", departure_date=DAY, wagon_number="125", departure_station=mill.station
    )
    payable = party_amount(mill.supplier, "payable", "we_owe", "RUB")
    stock = stock_qty(mill.wheat, mill.wheat_bin)[0]
    _open_money(mill, mill.cash, "15000")
    customs = CashOperation.objects.get(code="customs")
    payment = record_money(
        operation=customs,
        account=mill.cash,
        amount="15000",
        effective_date=DAY,
        order=spec,
        shipment=shipment,
    )
    assert money_balance(mill.cash) == 0
    assert party_amount(mill.supplier, "payable", "we_owe", "RUB") == payable
    assert stock_qty(mill.wheat, mill.wheat_bin)[0] == stock
    assert payment.order_id == spec.pk
    assert payment.shipment_id == shipment.pk
    assert payment.operation.category == CashOperation.Category.CUSTOMS
    assert OpenItem.objects.filter(document=payment.document).exists() is False
    other = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        lines=[{"product": mill.wheat, "quantity": "1", "price": "20"}],
    )
    other_wagon = record_shipment(
        order=other, quantity="1", departure_date=DAY, wagon_number="9", departure_station=mill.station
    )
    _open_money(mill, mill.cash, "100")
    with pytest.raises(ValidationError):
        record_money(
            operation=customs,
            account=mill.cash,
            amount="100",
            effective_date=DAY,
            order=spec,
            shipment=other_wagon,
        )
    assert money_balance(mill.cash) == Decimal("100")


def test_employee_advance_becomes_an_expense_only_when_confirmed(mill):
    contract = record_contract(supplier=mill.supplier, number="З-2026", contract_date=DAY)
    spec = record_purchase(
        supplier=mill.supplier,
        effective_date=DAY,
        contract=contract,
        specification_number="10",
        lines=[{"product": mill.wheat, "quantity": "10", "price": "20"}],
    )
    _accept(mill, spec, "10")
    shipment = record_shipment(
        order=spec, quantity="10", departure_date=DAY, wagon_number="125", departure_station=mill.station
    )
    wheat_debt = party_amount(mill.supplier, "payable", "we_owe", "KGS")
    employee = Party.objects.create(name="Экспедитор", is_employee=True)
    issued = CashOperation.objects.get(code="accountable-advance")
    returned = CashOperation.objects.get(code="accountable-return")
    customs = CashOperation.objects.get(code="customs")
    _open_money(mill, mill.cash, "50000")
    advance = record_money(operation=issued, account=mill.cash, amount="50000", effective_date=DAY, party=employee)
    assert money_balance(mill.cash) == 0
    assert party_amount(employee, "accountable", "they_owe", "KGS") == Decimal("50000")
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == wheat_debt
    assert MoneyMove.objects.filter(document=advance.document).count() == 1
    held = advance.document.open_items.get()
    confirmed = recognize_accountable(
        advance=held,
        operation=customs,
        amount="15000",
        effective_date=DAY,
        order=spec,
        shipment=shipment,
    )
    assert money_balance(mill.cash) == 0
    assert confirmed.order_id == spec.pk
    assert confirmed.shipment_id == shipment.pk
    assert MoneyMove.objects.filter(document=confirmed.document).exists() is False
    assert party_amount(employee, "accountable", "they_owe", "KGS") == Decimal("35000")
    assert party_amount(mill.supplier, "payable", "we_owe", "KGS") == wheat_debt
    record_money(operation=returned, account=mill.cash, amount="35000", effective_date=DAY, party=employee)
    assert money_balance(mill.cash) == Decimal("35000")
    assert party_amount(employee, "accountable", "they_owe", "KGS") == 0
    assert party_amount(employee, "receivable", "they_owe", "KGS") == 0
