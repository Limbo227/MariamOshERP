from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import Organization, Party, User
from apps.core.services import record_opening
from apps.finance.models import CashOperation, MoneyAccount, OpenItem
from apps.finance.queries import money_balance, party_amount
from apps.inventory.models import Product, StockMove
from apps.procurement.models import PurchaseContract, PurchaseOrder, RailwayStation, Shipment
from apps.ui.access import ensure_boss_group

pytestmark = pytest.mark.django_db

DAY = "2026-11-01"


@pytest.fixture
def boss(db):
    user = User.objects.create_user("boss", password="Boss-pass-1")
    user.groups.add(ensure_boss_group())
    return user


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    return client


def post_ok(client, url, data):
    response = client.post(url, data)
    if response.status_code != 302:
        form = response.context.get("form") if response.context else None
        errors = form.errors.as_text() if form is not None else response.content.decode()[:1500]
        raise AssertionError(f"{response.status_code} {url}\n{errors}")
    return response


def test_anonymous_reference_page_redirects_to_login(client):
    response = client.get(reverse("product_list"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_clerk_cannot_open_or_post_reference_data(client):
    clerk = User.objects.create_user("clerk", password="Clerk-pass-1")
    client.force_login(clerk)
    assert client.get(reverse("product_list")).status_code == 403
    response = client.post(reverse("product_create"), {"sku": "X", "name": "Чужой"})
    assert response.status_code == 403


def test_invalid_purchase_shows_form_errors(boss_client):
    response = boss_client.post(reverse("purchase_create"), {"action": "post"})
    assert response.status_code == 200
    assert response.context["form"].errors


def test_workplace_covers_reference_buying_receipt_and_money(boss_client):
    post_ok(boss_client, reverse("company"), {"legal_name": "Мариам-Ош"})
    assert Organization.objects.get().legal_name == "Мариам-Ош"

    post_ok(
        boss_client,
        reverse("product_create"),
        {"sku": "SACK", "name": "Мешок", "kind": "SACK", "unit": "PCS", "active": "on"},
    )
    post_ok(
        boss_client,
        reverse("product_create"),
        {"sku": "WHEAT", "name": "Пшеница", "kind": "WHEAT", "unit": "KG", "active": "on"},
    )
    wheat = Product.objects.get(sku="WHEAT")
    sack = Product.objects.get(sku="SACK")

    post_ok(
        boss_client,
        reverse("party_create"),
        {"name": "Поставщик теста", "is_supplier": "on", "active": "on"},
    )
    supplier = Party.objects.get(name="Поставщик теста")

    post_ok(
        boss_client,
        reverse("warehouse_create"),
        {"code": "raw", "name": "Склад сырья", "kind": "RAW", "active": "on"},
    )
    from apps.inventory.models import Warehouse

    warehouse = Warehouse.objects.get(code="raw")
    post_ok(
        boss_client,
        reverse("location_create"),
        {"warehouse": warehouse.pk, "name": "Бурт", "active": "on"},
    )
    from apps.inventory.models import StorageLocation

    location = StorageLocation.objects.get(name="Бурт")

    for kind, name, currency in (
        ("CASH", "Касса RUB", "RUB"),
        ("BANK", "Банк RUB", "RUB"),
        ("CASH", "Касса KGS", "KGS"),
    ):
        post_ok(
            boss_client,
            reverse("account_create", kwargs={"kind": kind}),
            {"name": name, "kind": kind, "currency": currency, "overdraft_limit": "0", "active": "on"},
        )
    rub_cash = MoneyAccount.objects.get(name="Касса RUB")
    rub_bank = MoneyAccount.objects.get(name="Банк RUB")
    kgs_cash = MoneyAccount.objects.get(name="Касса KGS")

    post_ok(
        boss_client,
        reverse("purchase_create"),
        {
            "supplier": supplier.pk,
            "effective_date": DAY,
            "contract": "",
            "specification_number": "",
            "product": sack.pk,
            "quantity": "100",
            "price": "15",
            "currency": "KGS",
            "note": "",
            "action": "post",
        },
    )
    ordinary = PurchaseOrder.objects.get(contract__isnull=True, currency="KGS")
    assert ordinary.lines.get().product_id == sack.pk
    assert StockMove.objects.count() == 0
    assert OpenItem.objects.count() == 0

    post_ok(
        boss_client,
        reverse("contract_create"),
        {
            "supplier": supplier.pk,
            "number": "Д-15",
            "contract_date": DAY,
            "description": "Пшеница",
            "active": "on",
        },
    )
    contract = PurchaseContract.objects.get(number="Д-15")
    post_ok(
        boss_client,
        reverse("specification_create", args=[contract.pk]),
        {
            "supplier": supplier.pk,
            "effective_date": DAY,
            "contract": contract.pk,
            "specification_number": "С-1",
            "product": wheat.pk,
            "quantity": "1000",
            "price": "20",
            "currency": "RUB",
            "note": "",
            "action": "post",
        },
    )
    rub_order = PurchaseOrder.objects.get(contract=contract, specification_number="С-1")
    assert StockMove.objects.count() == 0
    assert OpenItem.objects.count() == 0

    station = RailwayStation.objects.create(name="Манас")
    post_ok(
        boss_client,
        reverse("shipment_create"),
        {
            "order": rub_order.pk,
            "departure_station": station.pk,
            "quantity": "1000",
            "wagon_count": "1",
            "departure_date": DAY,
            "wagon_number": "125-А",
            "arrival_date": "",
            "notes": "",
        },
    )
    shipment = Shipment.objects.get(wagons__wagon_number="125-А")
    assert shipment.status == Shipment.Status.DRAFT
    listed = boss_client.get(reverse("shipment_list"), {"status": "DRAFT"})
    assert listed.status_code == 200
    assert "125-А" in listed.content.decode()
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.DRAFT
    assert StockMove.objects.count() == 0
    assert OpenItem.objects.count() == 0
    detail = boss_client.get(reverse("shipment_detail", args=[shipment.pk]))
    assert "Черновик не меняет склад и долг" in detail.content.decode()
    drafts = boss_client.get(reverse("shipment_list"), {"status": "DRAFT"})
    assert "125-А" in drafts.content.decode()

    post_ok(
        boss_client,
        reverse("purchase_create"),
        {
            "supplier": supplier.pk,
            "effective_date": DAY,
            "contract": "",
            "specification_number": "",
            "product": wheat.pk,
            "quantity": "500",
            "price": "20",
            "currency": "KGS",
            "note": "",
            "action": "post",
        },
    )
    kgs_order = PurchaseOrder.objects.get(contract__isnull=True, currency="KGS", lines__product=wheat)

    for order, quantity in ((rub_order, "1000"), (kgs_order, "500")):
        preview = boss_client.post(
            reverse("receipt_create"),
            {
                "supplier": supplier.pk,
                "order": order.pk,
                "purchase_line": order.lines.get().pk,
                "warehouse": warehouse.pk,
                "location": location.pk,
                "quantity": quantity,
                "effective_date": DAY,
                "note": "",
                "action": "preview",
            },
        )
        assert preview.status_code == 200
        assert "Расчётный долг поставщику" in preview.content.decode()
        post_ok(
            boss_client,
            reverse("receipt_create"),
            {
                "supplier": supplier.pk,
                "order": order.pk,
                "purchase_line": order.lines.get().pk,
                "warehouse": warehouse.pk,
                "location": location.pk,
                "quantity": quantity,
                "effective_date": DAY,
                "note": "",
                "action": "post",
            },
        )

    stock = boss_client.get(reverse("stock_list"))
    stock_html = stock.content.decode()
    assert stock.status_code == 200
    assert "1 500" in stock_html and "кг" in stock_html
    finance = boss_client.get(reverse("finance_home"))
    finance_html = finance.content.decode()
    assert "20 000,00" in finance_html and "RUB" in finance_html
    assert "10 000,00" in finance_html and "KGS" in finance_html
    assert "30 000,00" not in finance_html
    assert party_amount(supplier, "payable", "we_owe", "RUB") == Decimal("20000.00")
    assert party_amount(supplier, "payable", "we_owe", "KGS") == Decimal("10000.00")

    record_opening(
        effective_date=date(2026, 11, 1),
        money=[
            {"account": rub_cash, "amount": "50000"},
            {"account": kgs_cash, "amount": "1095"},
        ],
    )
    debt = OpenItem.objects.get(order=rub_order, side=OpenItem.Side.WE_OWE)
    post_ok(
        boss_client,
        reverse("payment_create"),
        {
            "supplier": supplier.pk,
            "account": rub_cash.pk,
            "amount": "15000",
            "effective_date": "2026-11-02",
            "external_reference": "PP-1",
            "note": "",
            "action": "post",
            f"alloc-{debt.pk}": "10000",
        },
    )
    assert party_amount(supplier, "payable", "we_owe", "RUB") == Decimal("10000.00")
    assert party_amount(supplier, "payable", "they_owe", "RUB") == Decimal("5000.00")
    purchase_html = boss_client.get(reverse("purchase_detail", args=[rub_order.pk])).content.decode()
    assert "10 000,00" in purchase_html
    assert "5 000,00" in purchase_html or "5000" in purchase_html

    post_ok(
        boss_client,
        reverse("transfer_create"),
        {
            "account": rub_cash.pk,
            "counter_account": rub_bank.pk,
            "amount": "5000",
            "effective_date": "2026-11-03",
            "note": "",
        },
    )
    customs = CashOperation.objects.get(code="customs")
    post_ok(
        boss_client,
        reverse("expense_create"),
        {
            "operation": customs.pk,
            "account": rub_cash.pk,
            "amount": "100",
            "effective_date": "2026-11-04",
            "order": rub_order.pk,
            "shipment": shipment.pk,
            "note": "таможня",
        },
    )
    preview = boss_client.post(
        reverse("convert_create"),
        {
            "account": kgs_cash.pk,
            "counter_account": rub_bank.pk,
            "amount": "1095",
            "destination_amount": "1000",
            "effective_date": "2026-11-05",
            "note": "",
            "action": "preview",
        },
    )
    assert preview.status_code == 200
    assert "Курс: 1,095 KGS/RUB" in preview.content.decode()
    post_ok(
        boss_client,
        reverse("convert_create"),
        {
            "account": kgs_cash.pk,
            "counter_account": rub_bank.pk,
            "amount": "1095",
            "destination_amount": "1000",
            "effective_date": "2026-11-05",
            "note": "",
            "action": "post",
        },
    )
    assert money_balance(rub_cash) == Decimal("29900.00")
    assert money_balance(rub_bank) == Decimal("6000.00")
    assert money_balance(kgs_cash) == Decimal("0")

    pages = [
        reverse("dashboard"),
        reverse("company"),
        reverse("product_list"),
        reverse("product_detail", args=[wheat.pk]),
        reverse("party_list"),
        reverse("party_detail", args=[supplier.pk]),
        reverse("warehouse_list"),
        reverse("warehouse_detail", args=[warehouse.pk]),
        reverse("location_list"),
        reverse("location_detail", args=[location.pk]),
        reverse("bank_list"),
        reverse("cash_list"),
        reverse("account_detail", args=[rub_cash.pk]),
        reverse("purchase_list"),
        reverse("purchase_detail", args=[rub_order.pk]),
        reverse("contract_list"),
        reverse("contract_detail", args=[contract.pk]),
        reverse("shipment_list"),
        reverse("shipment_detail", args=[shipment.pk]),
        reverse("receipt_list"),
        reverse("receipt_create"),
        reverse("stock_list"),
        reverse("move_list"),
        reverse("finance_home"),
        reverse("payment_create"),
        reverse("transfer_create"),
        reverse("convert_create"),
        reverse("expense_create"),
        reverse("report_procurement"),
        reverse("report_shipments"),
        reverse("report_suppliers"),
        reverse("report_money"),
    ]
    from apps.finance.models import MoneyDocument
    from apps.inventory.models import GoodsReceipt

    receipt = GoodsReceipt.objects.filter(supplier=supplier).first()
    payment = MoneyDocument.objects.filter(party=supplier).first()
    pages.append(reverse("receipt_detail", args=[receipt.pk]))
    pages.append(reverse("money_detail", args=[payment.pk]))
    for url in pages:
        response = boss_client.get(url)
        assert response.status_code == 200, url
