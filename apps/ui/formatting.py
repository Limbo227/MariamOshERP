from apps.core.quantities import display_rate, q_money, q_qty
from apps.inventory.models import Product


def format_money(value):
    if value is None or value == "":
        return "—"
    amount = q_money(value)
    sign = "−" if amount < 0 else ""
    text = f"{abs(amount):,.2f}".replace(",", " ").replace(".", ",")
    return f"{sign}{text}"


def format_qty(value):
    if value is None or value == "":
        return "—"
    amount = q_qty(value)
    sign = "−" if amount < 0 else ""
    text = f"{abs(amount):,.3f}"
    whole, frac = text.split(".")
    whole = whole.replace(",", " ")
    frac = frac.rstrip("0")
    rendered = whole if not frac else f"{whole},{frac}"
    return f"{sign}{rendered}"


def format_rate(value):
    if value is None or value == "":
        return "—"
    text = f"{display_rate(value):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


_UNIT_LABELS = {
    "PCS": "шт",
    "KG": "кг",
    "L": "л",
    "BAG": "меш.",
}


def qty_with_weight(product, quantity):
    """«500 меш. (25 000 кг)» for sacked goods, «134 000 кг» for the rest."""
    text = f"{format_qty(quantity)} {unit_label(product.unit)}"
    if product.unit == Product.Unit.BAG and product.unit_weight_kg:
        return f"{text} ({format_qty(q_qty(quantity * product.unit_weight_kg))} кг)"
    return text


def unit_label(code):
    if not code:
        return ""
    if code in _UNIT_LABELS:
        return _UNIT_LABELS[code]
    try:
        return Product.Unit(code).label
    except ValueError:
        return str(code)
