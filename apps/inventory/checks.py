from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.inventory.models import Product, Warehouse


def ensure_packaging(product, quantity, bags):
    if product is None:
        return
    if product.kind == Product.Kind.FLOUR and product.unit == Product.Unit.KG:
        if bags is None or bags <= 0:
            raise ValidationError("Для муки укажите число мешков.")
        if product.package_kg is None or quantity != product.package_kg * bags:
            raise ValidationError("Масса муки должна равняться числу мешков на массу одного мешка.")
        return
    if product.kind == Product.Kind.FLOUR and product.unit == Product.Unit.BAG:
        if product.unit_weight_kg is None or product.unit_weight_kg <= 0:
            raise ValidationError("Укажите массу одного мешка, кг.")
        if bags is not None and bags != quantity:
            raise ValidationError("Для муки в мешках количество и есть число мешков. Вес мешка в сумму не умножают.")
        return
    if bags is not None:
        raise ValidationError("Число мешков заполняется только для муки.")


def sack_pieces(product, quantity, bags):
    """How many empty sacks a flour output consumes. Bag flour uses its quantity once."""
    if product is None or not product.sack_id:
        return None
    if product.kind == Product.Kind.FLOUR and product.unit == Product.Unit.BAG:
        whole = Decimal(quantity)
        if whole != whole.to_integral_value():
            raise ValidationError("Для муки в мешках количество должно быть целым числом мешков.")
        return int(whole)
    if not bags:
        return None
    return int(bags)


def ensure_location(product, location):
    if product is None or location is None:
        return
    finished = product.kind in (Product.Kind.FLOUR, Product.Kind.BYPRODUCT)
    if finished and location.warehouse.kind != Warehouse.Kind.FINISHED:
        raise ValidationError("Готовая продукция хранится на складе готовой продукции.")
    if not finished and location.warehouse.kind != Warehouse.Kind.RAW:
        raise ValidationError("Сырьё и материалы хранятся на складе сырья.")
