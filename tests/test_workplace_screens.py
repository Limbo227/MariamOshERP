from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import Organization, Party, User
from apps.core.services import record_opening
from apps.finance.models import ExpenseCategory, MoneyAccount, MoneyDocument, OpenItem
from apps.inventory.models import Product, ProductCategory, StockMove, Warehouse
from apps.inventory.queries import stock_qty
from apps.inventory.services import record_receipt
from apps.procurement.models import PurchaseOrder, RailwayStation, Shipment
from apps.procurement.services import (
    post_shipment,
    record_contract,
    record_purchase,
    record_shipment,
)
from apps.ui.access import ensure_boss_group

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 1)


@pytest.fixture
def boss_client(client):
    user = User.objects.create_user("boss-ui", password="Boss-pass-1")
    user.groups.add(ensure_boss_group())
    Organization.objects.create(legal_name="Мариам-Ош")
    client.force_login(user)
    return client


def test_wheat_summary_keeps_drafts_out_of_actuals(boss_client):
    supplier = Party.objects.create(name="Антера", is_supplier=True)
    wheat = Product.objects.create(
        sku="WHEAT-UI", name="Пшеница 3", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    contract = record_contract(supplier=supplier, number="Д-9", contract_date=DAY, currency="RUB")
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": wheat, "quantity": Decimal("1000"), "price": Decimal("20")}],
        currency="RUB",
        contract=contract,
        specification_number="1",
    )
    station = RailwayStation.objects.create(name="Манас")
    shipment = record_shipment(
        order=order,
        quantity=Decimal("400"),
        departure_station=station,
        wagon_count=1,
    )
    page = boss_client.get(reverse("wheat_summary"))
    html = page.content.decode()
    assert page.status_code == 200
    assert "Антера" in html
    assert "20 000,00" in html
    assert "Черновик, расчёт" in html
    assert "8 000,00" in html
    assert shipment.status == Shipment.Status.DRAFT
    assert OpenItem.objects.count() == 0
    exported = boss_client.get(reverse("wheat_export"))
    assert exported.status_code == 200
    assert "Антера" in exported.content.decode("utf-8-sig")
    assert "400" in exported.content.decode("utf-8-sig")


def test_complete_specification_blocks_new_shipment_without_touching_stock(boss_client):
    supplier = Party.objects.create(name="Поставщик", is_supplier=True)
    wheat = Product.objects.create(
        sku="WHEAT-2", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    contract = record_contract(supplier=supplier, number="Д-2", contract_date=DAY)
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": wheat, "quantity": Decimal("100"), "price": Decimal("10")}],
        contract=contract,
        specification_number="С",
    )
    response = boss_client.post(reverse("specification_status", args=[order.pk]), {"action": "complete"})
    assert response.status_code == 302
    order.refresh_from_db()
    assert order.operational_status == PurchaseOrder.OperationalStatus.COMPLETED
    assert StockMove.objects.count() == 0
    station = RailwayStation.objects.create(name="Ош")
    denied = boss_client.post(
        reverse("shipment_create"),
        {
            "order": order.pk,
            "departure_station": station.pk,
            "quantity": "10",
            "wagon_count": "1",
            "wagon_number": "",
            "arrival_date": "",
            "notes": "",
        },
    )
    assert denied.status_code == 200
    assert Shipment.objects.count() == 0


def test_wagon_lines_do_not_change_posted_weight(boss_client):
    supplier = Party.objects.create(name="Зерно", is_supplier=True)
    wheat = Product.objects.create(
        sku="WHEAT-3", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    contract = record_contract(supplier=supplier, number="Д-3", contract_date=DAY, currency="KGS")
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": wheat, "quantity": Decimal("1000"), "price": Decimal("15")}],
        currency="KGS",
        contract=contract,
        specification_number="3",
    )
    station = RailwayStation.objects.create(name="Кара-Суу")
    shipment = record_shipment(
        order=order,
        quantity=Decimal("600"),
        departure_station=station,
        wagon_count=2,
        arrival_date=DAY,
    )
    post_shipment(shipment)
    before = OpenItem.objects.get().amount
    response = boss_client.post(
        reverse("shipment_wagons", args=[shipment.pk]),
        {
            "wagon_number": ["1", "2"],
            "weight_kg": ["200", "400"],
            "complete": "1",
        },
    )
    assert response.status_code == 302
    shipment.refresh_from_db()
    assert shipment.quantity == Decimal("600.000")
    assert shipment.wagons.count() == 2
    assert OpenItem.objects.get().amount == before
    detail = boss_client.get(reverse("shipment_detail", args=[shipment.pk]))
    assert "Принять товар по этой закупке" not in detail.content.decode()
    assert "Основное" not in detail.content.decode()


def test_directories_and_shipment_expense_use_existing_services(boss_client):
    supplier = Party.objects.create(name="Мешки", is_supplier=True)
    sack = Product.objects.create(
        sku="SACK-UI", name="Мешок", category=ProductCategory.objects.get(code="SACK"), unit=Product.Unit.PCS
    )
    Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": sack, "quantity": Decimal("10"), "price": Decimal("5")}],
        currency="KGS",
    )
    assert boss_client.post(
        reverse("category_create"),
        {"name": "Плёнка", "active": "on"},
    ).status_code == 302
    assert ProductCategory.objects.filter(name="Плёнка").exists()
    assert boss_client.post(
        reverse("expense_category_create"),
        {"name": "Простой вагонов", "active": "on"},
    ).status_code == 302
    category = ExpenseCategory.objects.get(name="Простой вагонов")
    account = MoneyAccount.objects.create(name="Касса KGS UI", kind=MoneyAccount.Kind.CASH, currency="KGS")
    record_opening(effective_date=DAY, money=[{"account": account, "amount": "1000"}])
    posted = boss_client.post(
        reverse("shipment_expense_create"),
        {
            "category": category.pk,
            "account": account.pk,
            "amount": "250",
            "effective_date": "2026-11-02",
            "order": order.pk,
            "note": "",
        },
    )
    assert posted.status_code == 302, posted.content.decode()[:500]
    assert MoneyDocument.objects.filter(expense_category=category, amount=Decimal("250.00")).exists()
    assert OpenItem.objects.filter(order=order).count() == 0
    stock = boss_client.get(reverse("stock_list"))
    assert "Основное" not in stock.content.decode()
    materials = boss_client.get(reverse("materials_monitor"))
    assert materials.status_code == 200
    assert "Мешок" in materials.content.decode()
    for name in (
        "directory_home",
        "station_list",
        "term_list",
        "unit_list",
        "operation_list",
        "customer_receipt_create",
        "specification_list",
    ):
        assert boss_client.get(reverse(name)).status_code == 200, name


def test_unused_specification_can_be_deleted(boss_client):
    supplier = Party.objects.create(name="Поставщик удаления", is_supplier=True)
    wheat = Product.objects.create(
        sku="WHEAT-DEL", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    contract = record_contract(supplier=supplier, number="Д-DEL", contract_date=DAY)
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": wheat, "quantity": Decimal("100"), "price": Decimal("10")}],
        contract=contract,
        specification_number="С-DEL",
    )
    page = boss_client.get(reverse("specification_list"))
    assert "Удалить" in page.content.decode()
    removed = boss_client.post(reverse("purchase_delete", args=[order.pk]))
    assert removed.status_code == 302
    assert not PurchaseOrder.objects.filter(pk=order.pk).exists()
    assert StockMove.objects.count() == 0
    assert OpenItem.objects.count() == 0


def test_specification_with_shipment_is_not_deleted(boss_client):
    supplier = Party.objects.create(name="Поставщик с поставкой", is_supplier=True)
    wheat = Product.objects.create(
        sku="WHEAT-KEEP", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    Warehouse.objects.create(code="raw-keep", name="Склад сырья", kind=Warehouse.Kind.RAW)
    contract = record_contract(supplier=supplier, number="Д-KEEP", contract_date=DAY)
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": wheat, "quantity": Decimal("100"), "price": Decimal("10")}],
        contract=contract,
        specification_number="С-KEEP",
    )
    station = RailwayStation.objects.create(name="Ош")
    record_shipment(order=order, quantity=Decimal("40"), departure_station=station, wagon_count=1)
    denied = boss_client.post(reverse("purchase_delete", args=[order.pk]))
    assert denied.status_code == 302
    order.refresh_from_db()
    assert order.document.state == "POSTED"
    assert StockMove.objects.count() == 0


def test_wheat_filter_lists_only_grain(boss_client):
    category = ProductCategory.objects.get(code="WHEAT")
    Product.objects.create(sku="GRAIN-F", name="Пшеница отбор", kind="GRAIN", category=category, unit="KG")
    Product.objects.create(sku="RAW-F", name="Премикс особый", kind="RAW", category=category, unit="KG")
    html = boss_client.get(reverse("wheat_summary")).content.decode()
    assert "Пшеница отбор" in html
    assert "Премикс особый" not in html


def test_new_specification_starts_from_an_active_contract(boss_client):
    supplier = Party.objects.create(name="Поставщик спецификации", is_supplier=True)
    opened = record_contract(supplier=supplier, number="ОТКР", contract_date=DAY)
    closed = record_contract(supplier=supplier, number="ЗАКР", contract_date=DAY)
    closed.active = False
    closed.save()
    page = boss_client.get(reverse("specification_list"))
    assert "Новая спецификация" in page.content.decode()
    picker = boss_client.get(reverse("specification_start"))
    html = picker.content.decode()
    assert "ОТКР" in html
    assert "ЗАКР" not in html
    response = boss_client.post(reverse("specification_start"), {"contract": opened.pk})
    assert response.status_code == 302
    assert response.url == reverse("specification_create", args=[opened.pk])


def _receipt_post(client, order, warehouse, quantity, **extra):
    return client.post(
        reverse("receipt_create"),
        {
            "supplier": order.supplier_id,
            "order": order.pk,
            "purchase_line": order.lines.get().pk,
            "warehouse": warehouse.pk,
            "quantity": quantity,
            "effective_date": "2026-11-02",
            "note": "",
            "action": "post",
            **extra,
        },
    )


def test_material_order_allows_extra_until_marked_done(boss_client):
    supplier = Party.objects.create(name="Мешки UI", is_supplier=True)
    sack = Product.objects.create(
        sku="SACK-UI", name="Мешок UI", category=ProductCategory.objects.get(code="WHEAT"), unit="PCS"
    )
    warehouse = Warehouse.objects.create(code="pack-ui", name="Склад мешков", kind=Warehouse.Kind.RAW)
    order = record_purchase(
        supplier=supplier,
        effective_date=DAY,
        lines=[{"product": sack, "quantity": Decimal("500"), "price": Decimal("10")}],
    )
    line = order.lines.get()
    record_receipt(
        supplier=supplier,
        warehouse=warehouse,
        effective_date=DAY,
        lines=[{"product": sack, "quantity": Decimal("500"), "purchase_line": line}],
    )
    listed = boss_client.get(reverse("materials_monitor")).content.decode()
    assert "В работе" in listed
    assert "100%" in listed
    warned = _receipt_post(boss_client, order, warehouse, "500")
    assert warned.status_code == 200
    assert "больше заказа" in warned.content.decode()
    assert stock_qty(sack)[0] == Decimal("500")
    posted = _receipt_post(boss_client, order, warehouse, "500", confirm_over="1")
    assert posted.status_code == 302
    assert stock_qty(sack)[0] == Decimal("1000")
    boss_client.post(reverse("specification_status", args=[order.pk]), {"action": "complete"})
    order.refresh_from_db()
    assert order.operational_status == PurchaseOrder.OperationalStatus.COMPLETED
    card = boss_client.get(reverse("purchase_detail", args=[order.pk])).content.decode()
    assert "Новую приёмку провести нельзя" in card
    assert "Принять товар" not in card
    blocked = _receipt_post(boss_client, order, warehouse, "500", confirm_over="1")
    assert blocked.status_code == 200
    assert "Заказ выполнен" in blocked.content.decode()
    assert stock_qty(sack)[0] == Decimal("1000")
