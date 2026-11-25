from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.core.models import Document
from apps.core.quantities import line_amount
from apps.finance.models import OpenItem
from apps.finance.queries import item_remaining, money_balance
from apps.inventory.models import ReceiptLine
from apps.procurement.models import PurchaseLine, Shipment


def fill_percent(planned, accepted):
    """Share of the ordered quantity already received, one decimal. None when there is no plan."""
    if not planned:
        return None
    return (Decimal(accepted) / Decimal(planned) * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def order_figures(order_ids):
    figures = {
        pk: {
            "planned_qty": Decimal("0"),
            "planned_amount": Decimal("0"),
            "dispatched_qty": Decimal("0"),
            "draft_qty": Decimal("0"),
            "accepted_qty": Decimal("0"),
            "accepted_amount": Decimal("0"),
            "paid": Decimal("0"),
            "outstanding": Decimal("0"),
            "outstanding_qty": Decimal("0"),
            "products": [],
        }
        for pk in order_ids
    }
    if not order_ids:
        return figures
    for line in PurchaseLine.objects.filter(order_id__in=order_ids).select_related("product"):
        row = figures[line.order_id]
        row["planned_qty"] += line.quantity
        row["planned_amount"] += line.amount
        if line.product.name not in row["products"]:
            row["products"].append(line.product.name)
    dispatched = (
        Shipment.objects.filter(order_id__in=order_ids, status=Shipment.Status.POSTED)
        .values("order_id")
        .annotate(total=Sum("quantity"))
    )
    for row in dispatched:
        figures[row["order_id"]]["dispatched_qty"] = row["total"] or Decimal("0")
    drafts = (
        Shipment.objects.filter(order_id__in=order_ids, status=Shipment.Status.DRAFT)
        .values("order_id")
        .annotate(total=Sum("quantity"))
    )
    for row in drafts:
        figures[row["order_id"]]["draft_qty"] = row["total"] or Decimal("0")
    accepted = ReceiptLine.objects.filter(
        purchase_line__order_id__in=order_ids,
        receipt__document__state=Document.State.POSTED,
        receipt__document__reversal__isnull=True,
    ).select_related("purchase_line")
    for line in accepted:
        row = figures[line.purchase_line.order_id]
        row["accepted_qty"] += line.quantity
        row["accepted_amount"] += line_amount(line.quantity, line.purchase_line.price)
    debts = OpenItem.objects.filter(
        order_id__in=order_ids,
        side=OpenItem.Side.WE_OWE,
        lane=OpenItem.Lane.PAYABLE,
        document__state=Document.State.POSTED,
        document__reversal__isnull=True,
    )
    for item in debts:
        left = item_remaining(item)
        row = figures[item.order_id]
        row["outstanding"] += left
        row["paid"] += item.amount - left
    for row in figures.values():
        row["outstanding_qty"] = row["planned_qty"] - row["accepted_qty"]
    return figures


def account_flow(account, start=None, end=None):
    from apps.finance.models import MoneyMove

    moves = MoneyMove.objects.filter(account=account)
    opening = Decimal("0")
    period = moves
    if start:
        opening = moves.filter(effective_date__lt=start).aggregate(total=Sum("amount_delta"))["total"] or Decimal("0")
        period = period.filter(effective_date__gte=start)
    if end:
        period = period.filter(effective_date__lte=end)
    inflows = period.filter(amount_delta__gt=0).aggregate(total=Sum("amount_delta"))["total"] or Decimal("0")
    raw_out = period.filter(amount_delta__lt=0).aggregate(total=Sum("amount_delta"))["total"] or Decimal("0")
    outflows = -raw_out
    return {
        "opening": opening,
        "inflows": inflows,
        "outflows": outflows,
        "closing": opening + inflows - outflows,
        "balance": money_balance(account),
    }
