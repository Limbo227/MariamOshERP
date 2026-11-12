from decimal import Decimal

from apps.core.quantities import q_qty


def weight_kg(unit_code, quantity, unit_weight_kg):
    """Physical kilograms for an inventory quantity.

    Kilograms convert 1:1. Other units use the stored weight of one unit.
    Unknown weight returns None instead of assuming a kilogram equivalent.
    """

    if quantity is None:
        return None
    quantity = q_qty(quantity)
    if unit_code == "KG":
        return quantity
    if unit_weight_kg is None:
        return None
    return q_qty(quantity * Decimal(unit_weight_kg))
