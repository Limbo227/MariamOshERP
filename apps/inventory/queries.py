from decimal import Decimal

from django.db.models import Sum

from apps.inventory.models import Product, StockMove
from apps.inventory.weights import weight_kg


def stock_qty(product, location=None):
    rows = StockMove.objects.filter(product=product)
    if location is not None:
        rows = rows.filter(location=location)
    quantity = rows.aggregate(total=Sum("qty_delta"))["total"] or Decimal("0")
    bags = rows.aggregate(total=Sum("bags_delta"))["total"]
    return quantity, bags


def stock_by_unit():
    """On-hand quantity summed from stock movements, one total per unit."""
    totals = (
        StockMove.objects.values("product__unit")
        .annotate(quantity=Sum("qty_delta"))
        .order_by("product__unit")
    )
    rows = []
    for row in totals:
        quantity = row["quantity"] or Decimal("0")
        if not quantity:
            continue
        unit = row["product__unit"]
        rows.append({"unit": unit, "label": Product.Unit(unit).label, "quantity": quantity})
    return rows


def stock_by_warehouse(warehouse=None, product=None, category=None, as_of=None):
    """On-hand quantity by warehouse and product. Storage locations stay internal.

    Optional filters only limit which movements are summed. They do not change
    how a movement was posted. ``as_of`` keeps movements on or before that date.
    """

    rows = StockMove.objects.select_related("product", "location__warehouse")
    if warehouse is not None:
        rows = rows.filter(location__warehouse=warehouse)
    if product is not None:
        rows = rows.filter(product=product)
    if category is not None:
        rows = rows.filter(product__category=category)
    if as_of is not None:
        rows = rows.filter(effective_date__lte=as_of)
    totals = {}
    for move in rows:
        key = (move.location.warehouse_id, move.product_id)
        bucket = totals.setdefault(
            key,
            {
                "warehouse": move.location.warehouse,
                "product": move.product,
                "quantity": Decimal("0"),
                "weight_kg": Decimal("0"),
                "weight_known": True,
            },
        )
        bucket["quantity"] += move.qty_delta
        part = weight_kg(move.unit_code or move.product.unit, move.qty_delta, move.unit_weight_kg)
        if part is None:
            bucket["weight_known"] = False
        else:
            bucket["weight_kg"] += part
    result = []
    for bucket in totals.values():
        if not bucket["quantity"] and not bucket["weight_kg"]:
            continue
        bucket["weight_kg"] = bucket["weight_kg"] if bucket["weight_known"] else None
        result.append(bucket)
    result.sort(key=lambda row: (row["warehouse"].name, row["product"].name))
    return result


def on_hand_weight_kg(product, location=None):
    rows = StockMove.objects.filter(product=product)
    if location is not None:
        rows = rows.filter(location=location)
    total = Decimal("0")
    seen = False
    for move in rows:
        part = weight_kg(
            move.unit_code or product.unit,
            move.qty_delta,
            move.unit_weight_kg if move.unit_weight_kg is not None else product.unit_weight_kg,
        )
        if part is None:
            return None
        total += part
        seen = True
    if not seen:
        return Decimal("0")
    return total

