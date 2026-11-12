from decimal import ROUND_HALF_UP, Decimal

MONEY = Decimal("0.01")
QTY = Decimal("0.001")
PRICE = Decimal("0.0001")
RATE = Decimal("0.000000000001")
RATE_DISPLAY = Decimal("0.000001")


def q_money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def q_qty(value):
    return Decimal(value).quantize(QTY, rounding=ROUND_HALF_UP)


def q_price(value):
    return Decimal(value).quantize(PRICE, rounding=ROUND_HALF_UP)


def line_amount(quantity, price):
    return (quantity * price).quantize(MONEY, rounding=ROUND_HALF_UP)


def q_rate(value):
    return Decimal(value).quantize(RATE, rounding=ROUND_HALF_UP)


def display_rate(value):
    return Decimal(value).quantize(RATE_DISPLAY, rounding=ROUND_HALF_UP)
