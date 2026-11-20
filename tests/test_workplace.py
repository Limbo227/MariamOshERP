from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import Organization, Party, User
from apps.core.quantities import q_money, q_qty
from apps.core.services import record_opening, reverse_document
from apps.finance.models import OpenItem
from apps.finance.queries import item_remaining, supplier_balances
from apps.finance.services import settle_supplier
from apps.inventory.models import Product, ProductCategory, StorageLocation, Warehouse
from apps.procurement.models import RailwayStation
from apps.procurement.services import record_contract, record_purchase, record_shipment
from apps.ui.access import ensure_boss_group

pytestmark = pytest.mark.django_db

DAY = date(2026, 11, 1)


@pytest.fixture
def boss():
    user = User.objects.create_user("boss", password="Boss-pass-1", is_staff=False, is_superuser=False)
    user.groups.add(ensure_boss_group())
    return user


def test_anonymous_dashboard_redirects_to_login(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_login_page_has_no_demo_account_hint(client):
    response = client.get(reverse("login"))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Вход" in html
    assert "Локальная демонстрация" not in html
    assert "Demo-" not in html


def test_clerk_cannot_open_dashboard(client):
    clerk = User.objects.create_user("clerk", password="Clerk-pass-1")
    client.force_login(clerk)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 403
    assert "Нет доступа" in response.content.decode()
    assert "Главная" in response.content.decode()


def test_inactive_boss_cannot_open_dashboard(client, boss):
    boss.is_active = False
    boss.save(update_fields=["is_active"])
    client.force_login(boss)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_superuser_can_open_empty_dashboard(client):
    admin = User.objects.create_superuser("root", "root@example.com", "Root-pass-1")
    client.force_login(admin)
    response = client.get(reverse("dashboard"))
    html = response.content.decode()
    assert response.status_code == 200
    assert response.context["supplier_count"] == 0
    assert response.context["payables"] == []
    assert response.context["advances"] == []
    assert "Пока нет закупок." in html
    assert reverse("product_list") in html
    assert reverse("purchase_list") in html
    assert reverse("shipment_list") in html
    assert reverse("finance_home") in html


def test_boss_login_logout_and_live_dashboard(client, boss):
    Organization.objects.create(legal_name="Мариам-Ош")
    raw = Warehouse.objects.create(code="raw", name="Склад сырья", kind=Warehouse.Kind.RAW)
    wheat_bin = StorageLocation.objects.create(warehouse=raw, name="Пшеница")
    sack_bin = StorageLocation.objects.create(warehouse=raw, name="Мешки")
    wheat = Product.objects.create(
        sku="WHEAT", name="Пшеница", category=ProductCategory.objects.get(code="WHEAT"), unit=Product.Unit.KG
    )
    sack = Product.objects.create(
        sku="SACK", name="Пустой мешок", category=ProductCategory.objects.get(code="SACK"), unit=Product.Unit.PCS
    )
    supplier = Party.objects.create(name="Антера", is_supplier=True)
    record_opening(
        effective_date=DAY,
        stock=[
            {"product": wheat, "location": wheat_bin, "quantity": Decimal("1500")},
            {"product": sack, "location": sack_bin, "quantity": Decimal("40")},
        ],
        parties=[
            {"party": supplier, "side": OpenItem.Side.WE_OWE, "lane": OpenItem.Lane.PAYABLE, "amount": "1000.00", "currency": "RUB"},
            {"party": supplier, "side": OpenItem.Side.THEY_OWE, "lane": OpenItem.Lane.PAYABLE, "amount": "400.00", "currency": "RUB"},
            {"party": supplier, "side": OpenItem.Side.THEY_OWE, "lane": OpenItem.Lane.PAYABLE, "amount": "50.00", "currency": "KGS"},
        ],
    )
    debt = OpenItem.objects.get(party=supplier, side=OpenItem.Side.WE_OWE, currency="RUB")
    settle_supplier(
        party=supplier,
        effective_date=date(2026, 11, 2),
        allocations=[{"item": debt, "amount": Decimal("200.00")}],
    )
    contract = record_contract(supplier=supplier, number="Д-1", contract_date=DAY)
    order = record_purchase(
        supplier=supplier,
        effective_date=date(2026, 11, 3),
        lines=[{"product": wheat, "quantity": Decimal("1000"), "price": Decimal("20")}],
        currency="RUB",
        contract=contract,
        specification_number="8",
    )
    station = RailwayStation.objects.create(name="Манас")
    record_shipment(
        order=order,
        quantity=Decimal("600"),
        departure_date=date(2026, 11, 4),
        wagon_number="51234567",
        departure_station=station,
    )
    cancelled = record_purchase(
        supplier=supplier,
        effective_date=date(2026, 11, 3),
        lines=[{"product": sack, "quantity": Decimal("10"), "price": Decimal("15")}],
        currency="KGS",
    )
    reverse_document(cancelled.document, effective_date=date(2026, 11, 5))

    logged_out = client.post(reverse("login"), {"username": "boss", "password": "wrong-pass"})
    assert logged_out.status_code == 200
    logged_in = client.post(reverse("login"), {"username": "boss", "password": "Boss-pass-1"})
    assert logged_in.status_code == 302
    assert logged_in.url == reverse("dashboard")

    response = client.get(reverse("dashboard"))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Мариам-Ош" in html
    assert response.context["supplier_count"] == 1
    assert response.context["purchase_count"] == 1
    assert response.context["shipments_in_transit"] == 1
    assert response.context["shipments_at_customs"] == 0
    assert response.context["shipments_arrived"] == 0
    stock = {row["unit"]: q_qty(row["quantity"]) for row in response.context["stock"]}
    assert stock == {"KG": q_qty("1500"), "PCS": q_qty("40")}
    payables = {row["currency"]: q_money(row["amount"]) for row in response.context["payables"]}
    advances = {row["currency"]: q_money(row["amount"]) for row in response.context["advances"]}
    assert payables == {"RUB": q_money("800.00")}
    assert advances == {"RUB": q_money("200.00"), "KGS": q_money("50.00")}
    assert "800,00" in html and "RUB" in html
    assert "50,00" in html and "KGS" in html
    assert "1 050,00" not in html
    assert "1 500" in html and "кг" in html and "шт" in html
    assert "1 540" not in html
    assert "Д-1 / 8" in html
    assert "51234567" in html
    assert "Сторнирована" in html
    assert order.document.number in html

    expected_payable = {}
    expected_advances = {}
    for item in OpenItem.objects.filter(lane=OpenItem.Lane.PAYABLE):
        left = item_remaining(item)
        if left <= 0:
            continue
        bucket = expected_payable if item.side == OpenItem.Side.WE_OWE else expected_advances
        bucket[item.currency] = bucket.get(item.currency, Decimal("0")) + left
    mirrored = supplier_balances()
    assert {row["currency"]: row["amount"] for row in mirrored["payable"]} == expected_payable
    assert {row["currency"]: row["amount"] for row in mirrored["advances"]} == expected_advances

    client.post(reverse("logout"))
    assert client.get(reverse("dashboard")).status_code == 302
