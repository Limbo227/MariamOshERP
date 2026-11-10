from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.catalog.models import Product, ProductRequirement
from apps.core.access import ensure_group
from apps.core.models import Company, Membership, User, WarehouseGrant
from apps.inventory.models import OpeningLine, StorageLocation, Warehouse

VIEW_PERMS = [
    "core.view_workspace",
    "catalog.view_product",
    "catalog.view_supplier",
    "inventory.view_warehouse",
    "inventory.view_storagelocation",
    "inventory.view_stockledgerentry",
    "inventory.view_openingbalance",
]


def _person(username, company, permissions, warehouses):
    group = ensure_group(f"test-{username}", permissions)
    user = User.objects.create_user(username=username, password="Demo-user-1", first_name=username, last_name="Демо")
    membership = Membership.objects.create(user=user, company=company, role=group)
    for warehouse in warehouses:
        WarehouseGrant.objects.create(membership=membership, warehouse=warehouse)
    return user, membership


@pytest.fixture
def world(db):
    company = Company.objects.create(name="Мариам-Ош", code="test-mill")
    raw = Warehouse.objects.create(company=company, kind=Warehouse.Kind.RAW, name="Склад сырья")
    finished = Warehouse.objects.create(company=company, kind=Warehouse.Kind.FINISHED, name="Склад готовой продукции")
    section_a = StorageLocation.objects.create(warehouse=raw, name="Секция A", is_default=True)
    packaging = StorageLocation.objects.create(warehouse=raw, name="Упаковка и материалы")
    finished_location = StorageLocation.objects.create(warehouse=finished, name="Готовая продукция", is_default=True)
    wheat = Product.objects.create(company=company, sku="WHEAT-4", name="Пшеница", kind=Product.Kind.WHEAT, unit=Product.Unit.KG, grade="4")
    sack = Product.objects.create(company=company, sku="SACK-50", name="Мешок", kind=Product.Kind.SACK, unit=Product.Unit.PCS)
    flour = Product.objects.create(
        company=company, sku="FLOUR-50", name="Мука", kind=Product.Kind.FLOUR, unit=Product.Unit.KG, package_kg=Decimal("50"), grade="высший"
    )
    ProductRequirement.objects.create(product=flour, component=sack)
    storage_user, storage_membership = _person("storage", company, [*VIEW_PERMS, "inventory.add_openingbalance"], [raw, finished])
    customs_user, _customs_membership = _person("customs", company, VIEW_PERMS, [raw, finished])
    return SimpleNamespace(
        company=company,
        raw=raw,
        finished=finished,
        section_a=section_a,
        packaging=packaging,
        finished_location=finished_location,
        wheat=wheat,
        sack=sack,
        flour=flour,
        storage_user=storage_user,
        storage_membership=storage_membership,
        customs_user=customs_user,
        today=date(2026, 2, 1),
        basis=OpeningLine.Basis.COUNTED,
        weighed=OpeningLine.Basis.WEIGHED,
    )
