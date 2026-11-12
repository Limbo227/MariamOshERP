from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.audit import write_audit
from apps.core.models import AuditEntry
from apps.core.services import require_active
from apps.inventory.models import Product, ProductCategory, UnitOfMeasure
from apps.inventory.reference_data import seed_categories, seed_units
from apps.procurement.services import _code


def list_units():
    return UnitOfMeasure.objects.filter(active=True).order_by("code")


def ensure_reference_units():
    seed_units(UnitOfMeasure)
    seed_categories(ProductCategory)


@transaction.atomic
def save_category(*, name, code="", description="", active=True, role=ProductCategory.Role.OTHER, category=None, actor=None):
    name = (name or "").strip()
    if not name:
        raise ValidationError("Укажите название категории.")
    if role not in ProductCategory.Role.values:
        raise ValidationError("Неизвестная техническая роль категории.")
    created = category is None
    if created:
        category = ProductCategory(
            name=name,
            code=(code or "").strip() or _code(ProductCategory, name, "CAT"),
            role=role,
        )
    else:
        category = ProductCategory.objects.select_for_update().get(pk=category.pk)
        if code:
            category.code = code.strip()
        if category.products.exists() and category.role != role:
            raise ValidationError("Нельзя менять техническую роль категории, в которой уже есть товары.")
        category.role = role
    category.name = name
    category.description = description or ""
    category.active = active
    category.save()
    write_audit(
        action=AuditEntry.Action.CREATED if created else AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="product_category",
        target_id=category.pk,
        detail=category.name,
    )
    return category


@transaction.atomic
def deactivate_category(category, *, actor=None):
    category = ProductCategory.objects.select_for_update().get(pk=category.pk)
    category.active = False
    category.save(update_fields=["active"])
    write_audit(
        action=AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="product_category",
        target_id=category.pk,
        detail="Категория отключена.",
    )
    return category


@transaction.atomic
def save_product(
    *,
    sku,
    name,
    category,
    unit,
    unit_weight_kg=None,
    package_kg=None,
    sack=None,
    active=True,
    product=None,
    actor=None,
):
    require_active(category)
    unit_code = unit.code if isinstance(unit, UnitOfMeasure) else str(unit)
    created = product is None
    if created:
        product = Product(sku=sku, name=name, category=category, unit=unit_code)
    else:
        product = Product.objects.select_for_update().get(pk=product.pk)
        product.sku = sku
        product.name = name
        product.category = category
        product.unit = unit_code
    product.unit_weight_kg = unit_weight_kg
    product.package_kg = package_kg
    product.sack = sack
    product.active = active
    product.kind = category.role
    product.save()
    write_audit(
        action=AuditEntry.Action.CREATED if created else AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="product",
        target_id=product.pk,
        detail=product.name,
    )
    return product
