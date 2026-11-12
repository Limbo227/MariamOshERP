from decimal import Decimal

from django.db.models import Q, Sum

from apps.core.quantities import MONEY
from apps.finance.models import Allocation, MoneyMove, OpenItem


def item_remaining(item):
    used = (
        Allocation.objects.filter(
            Q(we_owe=item) | Q(they_owe=item),
            reversal_of__isnull=True,
            reversal__isnull=True,
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    return (item.amount - used).quantize(MONEY)


def party_position(party):
    """Open supplier debt and open customer debt, kept apart by currency."""

    lanes = {
        OpenItem.Lane.PAYABLE: {},
        OpenItem.Lane.RECEIVABLE: {},
        OpenItem.Lane.ACCOUNTABLE: {},
    }
    items = []
    for item in OpenItem.objects.filter(party=party).order_by("effective_date", "pk"):
        left = item_remaining(item)
        if left <= 0:
            continue
        items.append((item, left))
        bucket = lanes[item.lane].setdefault(item.currency, {"we_owe": Decimal("0"), "they_owe": Decimal("0")})
        key = "we_owe" if item.side == OpenItem.Side.WE_OWE else "they_owe"
        bucket[key] += left
    return {
        "payable": lanes[OpenItem.Lane.PAYABLE],
        "receivable": lanes[OpenItem.Lane.RECEIVABLE],
        "accountable": lanes[OpenItem.Lane.ACCOUNTABLE],
        "items": items,
    }


def party_amount(party, lane, side, currency):
    return party_position(party)[lane].get(currency, {}).get(side, Decimal("0"))


def money_balance(account):
    return MoneyMove.objects.filter(account=account).aggregate(total=Sum("amount_delta"))["total"] or Decimal("0")


def supplier_balances():
    """Open supplier debt and advances, split by currency.

    The remainder is the same rule as item_remaining: the posted amount minus
    allocations that are not reversals and have not themselves been reversed.
    """
    items = list(OpenItem.objects.filter(lane=OpenItem.Lane.PAYABLE).only("id", "amount", "side", "currency"))
    used = {}
    if items:
        ids = {item.pk for item in items}
        allocations = Allocation.objects.filter(
            Q(we_owe_id__in=ids) | Q(they_owe_id__in=ids),
            reversal_of__isnull=True,
            reversal__isnull=True,
        ).values_list("we_owe_id", "they_owe_id", "amount")
        for we_owe_id, they_owe_id, amount in allocations:
            if we_owe_id in ids:
                used[we_owe_id] = used.get(we_owe_id, Decimal("0")) + amount
            if they_owe_id in ids and they_owe_id != we_owe_id:
                used[they_owe_id] = used.get(they_owe_id, Decimal("0")) + amount
    payable = {}
    advances = {}
    for item in items:
        left = (item.amount - used.get(item.pk, Decimal("0"))).quantize(MONEY)
        if left <= 0:
            continue
        bucket = payable if item.side == OpenItem.Side.WE_OWE else advances
        bucket[item.currency] = bucket.get(item.currency, Decimal("0")) + left
    return {"payable": _money_rows(payable), "advances": _money_rows(advances)}


def _money_rows(bucket):
    return [
        {"currency": currency, "amount": amount.quantize(MONEY)}
        for currency, amount in sorted(bucket.items())
    ]

