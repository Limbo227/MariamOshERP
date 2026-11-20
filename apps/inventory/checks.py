from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.inventory.models import Product


def ensure_packaging(product, quantity, bags):
    if product is None:
        return
    if product.unit == Product.Unit.KG and product.package_kg:
        if bags is None or bags <= 0:
            raise ValidationError("Для товара с массой мешка укажите число мешков.")
        if quantity != product.package_kg * bags:
            raise ValidationError("Масса должна равняться числу мешков на массу одного мешка.")
        return
    if product.unit == Product.Unit.BAG:
        if product.unit_weight_kg is None or product.unit_weight_kg <= 0:
            raise ValidationError("Укажите массу одного мешка, кг.")
        if bags is not None and bags != quantity:
            raise ValidationError("Для товара в мешках количество и есть число мешков. Вес мешка в сумму не умножают.")
        return
    if bags is not None:
        raise ValidationError("Число мешков заполняется для товара в мешках или с указанной массой мешка.")


def sack_pieces(product, quantity, bags):
    """How many empty sacks a packed output consumes. Bag stock uses its quantity once."""
    if product is None or not product.sack_id:
        return None
    if product.unit == Product.Unit.BAG:
        whole = Decimal(quantity)
        if whole != whole.to_integral_value():
            raise ValidationError("Для товара в мешках количество должно быть целым числом мешков.")
        return int(whole)
    if not bags:
        return None
    return int(bags)


def ensure_location(product, location):
    if product is None or location is None:
        return
    allowed = location.warehouse.category_id
    if allowed is None or product.category_id == allowed:
        return
    raise ValidationError(
        f"Склад «{location.warehouse}» принимает только категорию «{location.warehouse.category}»."
    )
