"""Reasons a directory record must stay switched on.

A warehouse with goods, a product still on hand, a party with open debt or advance and a
money account that still holds money cannot be switched off: they would vanish from the
pick lists while the balance is still there.
"""

from django.db.models import Sum

from apps.core.models import Party
from apps.finance.models import MoneyAccount
from apps.finance.queries import money_balance, party_position
from apps.inventory.models import Product, StockMove, Warehouse
from apps.ui.formatting import format_money, format_qty, unit_label


def _stock_rows(**filters):
    rows = (
        StockMove.objects.filter(**filters)
        .values("product__name", "product__unit")
        .annotate(total=Sum("qty_delta"))
        .exclude(total=0)
        .order_by("product__name")
    )
    return [f"{format_qty(row['total'])} {unit_label(row['product__unit'])} «{row['product__name']}»" for row in rows]


def disable_blocker(obj):
    """Text explaining why obj cannot be switched off, or an empty string."""
    if isinstance(obj, Warehouse):
        rows = _stock_rows(location__warehouse=obj)
        if rows:
            return (
                f"На складе «{obj.name}» есть остаток: {', '.join(rows[:3])}"
                f"{' и другое' if len(rows) > 3 else ''}. Отключить склад можно, когда он пуст."
            )
    elif isinstance(obj, Product):
        rows = _stock_rows(product=obj)
        if rows:
            return f"Товар есть на складе: {', '.join(rows)}. Отключить товар можно, когда остаток 0."
    elif isinstance(obj, Party):
        position = party_position(obj)
        parts = []
        for lane in ("payable", "receivable", "accountable"):
            for currency, bucket in position[lane].items():
                if bucket["we_owe"]:
                    parts.append(f"мы должны {format_money(bucket['we_owe'])} {currency}")
                if bucket["they_owe"]:
                    parts.append(f"нам должны {format_money(bucket['they_owe'])} {currency}")
        if parts:
            return (
                f"У «{obj.name}» открыты расчёты: {', '.join(parts)}. "
                "Отключить контрагента можно, когда расчёты закрыты."
            )
    elif isinstance(obj, MoneyAccount):
        balance = money_balance(obj)
        if balance:
            return (
                f"На счёте «{obj.name}» остаток {format_money(balance)} {obj.currency}. "
                "Отключить счёт можно, когда остаток 0."
            )
    return ""
