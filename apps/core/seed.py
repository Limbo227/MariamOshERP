from datetime import date
from decimal import Decimal
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.catalog.models import OriginStation, Product, ProductRequirement, Supplier
from apps.core.access import ensure_group
from apps.core.models import Company, Membership, WarehouseGrant
from apps.inventory.models import OpeningBalance, OpeningLine, StorageLocation, Warehouse
from apps.inventory.services import DraftLine, create_draft, post_opening

DEMO_OPENING_KEY = UUID("11111111-1111-4111-8111-111111111111")
DEMO_PASSWORDS = {
    "admin": "Demo-admin-1",
    "supply": "Demo-supply-1",
    "customs": "Demo-customs-1",
    "storage": "Demo-storage-1",
}
SECTION_A = "Секция A"
SECTION_B = "Секция B"
PACKAGING = "Упаковка и материалы"
FINISHED_LOCATION = "Готовая продукция"

VIEW_PERMS = [
    "core.view_workspace",
    "catalog.view_product",
    "catalog.view_supplier",
    "inventory.view_warehouse",
    "inventory.view_storagelocation",
    "inventory.view_stockledgerentry",
    "inventory.view_openingbalance",
]
SUPPLY_PERMS = [
    "core.view_workspace",
    "catalog.view_product",
    "catalog.add_product",
    "catalog.change_product",
    "catalog.view_supplier",
    "catalog.add_supplier",
    "catalog.view_originstation",
    "catalog.add_originstation",
    "procurement.view_supplycontract",
    "procurement.add_supplycontract",
    "procurement.view_contractline",
    "procurement.add_contractline",
    "procurement.view_contractshipment",
    "procurement.add_contractshipment",
    "procurement.view_factoryarrival",
    "procurement.add_factoryarrival",
    "procurement.view_contractpayment",
    "procurement.add_contractpayment",
]
CUSTOMS_PERMS = [
    *VIEW_PERMS,
    "procurement.view_purchaseorder",
    "procurement.view_shipment",
    "procurement.add_shipment",
    "procurement.change_shipment",
    "procurement.view_transportunit",
    "procurement.add_transportunit",
    "procurement.view_purchasecharge",
    "procurement.add_purchasecharge",
    "procurement.view_chargepayment",
    "procurement.add_chargepayment",
    "procurement.view_customsacceptance",
    "procurement.add_customsacceptance",
    "quality.view_supplierqualityvalue",
    "quality.view_exceptionrecord",
    "inventory.view_goodsreceipt",
]
STORAGE_PERMS = [
    *VIEW_PERMS,
    "inventory.add_openingbalance",
    "procurement.view_purchaseorder",
    "procurement.view_shipment",
    "procurement.view_transportunit",
    "inventory.view_goodsreceipt",
    "inventory.add_goodsreceipt",
    "inventory.view_stockadjustment",
    "inventory.add_stockadjustment",
    "quality.view_qualityinspection",
    "quality.add_qualityinspection",
    "quality.view_localqualityvalue",
    "quality.add_localqualityvalue",
    "quality.view_exceptionrecord",
]


def seed():
    with transaction.atomic():
        company, _created = Company.objects.get_or_create(
            code="mariam-osh",
            defaults={"name": "Мариам-Ош", "timezone": "Asia/Bishkek"},
        )
        groups = {
            "supply": ensure_group("Снабжение", SUPPLY_PERMS),
            "customs": ensure_group("Таможня", CUSTOMS_PERMS),
            "storage": ensure_group("Производство и склад", STORAGE_PERMS),
        }
        _ensure_user("admin", first_name="Технический", last_name="администратор", superuser=True)
        memberships = {}
        for username, first_name, group_key in (
            ("supply", "Снабжение", "supply"),
            ("customs", "Таможня", "customs"),
            ("storage", "Склад", "storage"),
        ):
            user = _ensure_user(username, first_name=first_name, last_name="Демо")
            membership, _created = Membership.objects.get_or_create(
                user=user,
                company=company,
                defaults={"role": groups[group_key]},
            )
            if membership.role_id != groups[group_key].id:
                membership.role = groups[group_key]
                membership.save(update_fields=["role"])
            memberships[username] = membership

        raw, _created = Warehouse.objects.get_or_create(
            company=company, kind=Warehouse.Kind.RAW, defaults={"name": "Склад сырья"}
        )
        finished, _created = Warehouse.objects.get_or_create(
            company=company, kind=Warehouse.Kind.FINISHED, defaults={"name": "Склад готовой продукции"}
        )
        locations = {}
        for warehouse, name, is_default in (
            (raw, SECTION_A, True),
            (raw, SECTION_B, False),
            (raw, PACKAGING, False),
            (finished, FINISHED_LOCATION, True),
        ):
            location, _created = StorageLocation.objects.get_or_create(
                warehouse=warehouse,
                name=name,
                defaults={"is_default": is_default, "active": True},
            )
            locations[name] = location
        for membership in memberships.values():
            for warehouse in (raw, finished):
                WarehouseGrant.objects.get_or_create(membership=membership, warehouse=warehouse)

        products = {}
        for sku, fields in _products():
            product, _created = Product.objects.get_or_create(company=company, sku=sku, defaults=fields)
            products[sku] = product
        ProductRequirement.objects.get_or_create(
            product=products["FLOUR-50"],
            defaults={"component": products["SACK-50"], "quantity": 1},
        )
        Supplier.objects.get_or_create(company=company, reference="SYN-GRAIN", defaults={"name": "ТОО «Синтетика-Зерно»"})
        Supplier.objects.get_or_create(company=company, reference="SYN-SACK", defaults={"name": "ОсОО «Синтетика-Тара»"})

        storage = memberships["storage"]
        try:
            OpeningBalance.objects.get(company=company, key=DEMO_OPENING_KEY)
        except OpeningBalance.DoesNotExist:
            create_draft(
                membership=storage,
                actor=storage.user,
                warehouse_id=raw.pk,
                reference="СИНТЕТИКА: начальные остатки для демонстрации, не данные завода",
                effective_date=date(2026, 1, 1),
                lines=[
                    DraftLine(products["WHEAT-4"].pk, locations[SECTION_A].pk, Decimal("8000"), None, OpeningLine.Basis.WEIGHED),
                    DraftLine(products["WHEAT-5"].pk, locations[SECTION_B].pk, Decimal("2000"), None, OpeningLine.Basis.WEIGHED),
                    DraftLine(products["SACK-50"].pk, locations[PACKAGING].pk, Decimal("500"), None, OpeningLine.Basis.COUNTED),
                ],
                key=DEMO_OPENING_KEY,
            )
        post_opening(membership=storage, actor=storage.user, document_id=OpeningBalance.objects.get(company=company, key=DEMO_OPENING_KEY).pk)
        for name in ("ДЖАРКУЛЬ", "КОСТАНАЙ", "ЖАНЫСПАЙ", "САРЫКОЛЬ", "АМАНКАРАГАЙ", "ЖАНА-ЕСИЛЬ", "ЕСИЛЬ", "УГОЛКИ", "АРКАЛЫК"):
            OriginStation.objects.get_or_create(company=company, name=name)
        get_user_model().objects.filter(username__in=["customs", "storage"]).update(is_active=False)


def _ensure_user(username, *, first_name, last_name, superuser=False):
    user, created = get_user_model().objects.get_or_create(
        username=username,
        defaults={"first_name": first_name, "last_name": last_name, "is_staff": superuser, "is_superuser": superuser},
    )
    if created:
        user.set_password(DEMO_PASSWORDS[username])
        user.save(update_fields=["password"])
    return user


def _products():
    return [
        ("WHEAT-4", {"name": "Пшеница 4 класс (синтетика)", "grade": "4", "kind": Product.Kind.WHEAT, "unit": Product.Unit.KG}),
        ("WHEAT-5", {"name": "Пшеница 5 класс (синтетика)", "grade": "5", "kind": Product.Kind.WHEAT, "unit": Product.Unit.KG}),
        ("SACK-50", {"name": "Мешок пустой 50 кг (синтетика)", "grade": "", "kind": Product.Kind.SACK, "unit": Product.Unit.PCS}),
        ("FLOUR-50", {"name": "Мука 50 кг (синтетика)", "grade": "высший", "kind": Product.Kind.FLOUR, "unit": Product.Unit.KG, "package_kg": Decimal("50")}),
        ("BRAN-KG", {"name": "Отруби, кг (синтетика, без остатка)", "grade": "", "kind": Product.Kind.BYPRODUCT, "unit": Product.Unit.KG}),
    ]
