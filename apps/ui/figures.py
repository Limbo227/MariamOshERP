from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum

from apps.core.models import Document
from apps.core.quantities import line_amount
from apps.finance.models import Allocation, OpenItem
from apps.finance.queries import item_remaining, money_balance, party_position
from apps.inventory.models import GoodsReceipt, ReceiptLine
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


def specification_statement(order):
    """Поставки with the debt each one still carries, and the payments that closed them."""
    line = order.lines.select_related("product").first()
    price = line.price if line is not None else None
    product = line.product if line is not None else None
    shipments = list(
        order.shipments.select_related("departure_station", "receipt__document").order_by(
            "departure_date", "arrival_date", "pk"
        )
    )
    by_document = {}
    for shipment in shipments:
        if shipment.receipt_id:
            by_document[shipment.receipt.document_id] = shipment
    arrivals = []
    for shipment in shipments:
        item = _debt_item(shipment.receipt.document_id, order) if shipment.receipt_id else None
        amount = item.amount if item is not None else (line_amount(shipment.quantity, price) if price else None)
        left = item_remaining(item) if item is not None else None
        arrivals.append(
            {
                "kind": "shipment",
                "shipment": shipment,
                "receipt": shipment.receipt,
                "station": shipment.departure_station,
                "departure": shipment.departure_date,
                "arrival": shipment.arrival_date,
                "wagons": shipment.wagon_count,
                "quantity": shipment.quantity,
                "amount": amount,
                "closed": None if left is None or amount is None else amount - left,
                "left": left,
                "status": shipment.get_status_display(),
                "posted": shipment.status == Shipment.Status.POSTED,
            }
        )
    manuals = (
        GoodsReceipt.objects.filter(lines__purchase_line__order=order, source_shipment__isnull=True)
        .select_related("document", "warehouse")
        .distinct()
        .order_by("document__effective_date", "pk")
    )
    for receipt in manuals:
        if receipt.document_id in by_document:
            continue
        quantity = sum(
            (row.quantity for row in receipt.lines.filter(purchase_line__order=order)),
            Decimal("0"),
        )
        item = _debt_item(receipt.document_id, order)
        amount = item.amount if item is not None else (line_amount(quantity, price) if price else None)
        left = item_remaining(item) if item is not None else None
        arrivals.append(
            {
                "kind": "receipt",
                "shipment": None,
                "receipt": receipt,
                "station": None,
                "departure": None,
                "arrival": receipt.document.effective_date,
                "wagons": None,
                "quantity": quantity,
                "amount": amount,
                "closed": None if left is None or amount is None else amount - left,
                "left": left,
                "status": "Отменена" if Document.objects.filter(reverses=receipt.document).exists() else "Проведена",
                "posted": receipt.document.state == Document.State.POSTED,
            }
        )
    payments = _payment_rows(order, by_document)
    shown = {row["item"].pk for row in payments}
    loose_advances = []
    for item in OpenItem.objects.filter(
        party_id=order.supplier_id,
        side=OpenItem.Side.THEY_OWE,
        lane=OpenItem.Lane.PAYABLE,
        currency=order.currency,
        document__state=Document.State.POSTED,
        document__reversal__isnull=True,
    ).select_related("document__money"):
        if item.pk in shown:
            continue
        left = item_remaining(item)
        if left <= 0:
            continue
        loose_advances.append(
            {"item": item, "left": left, "document": item.document, "money": _money_of(item.document)}
        )
    position = party_position(order.supplier)["payable"].get(order.currency, {})
    debt_left = sum((row["left"] or Decimal("0") for row in arrivals), Decimal("0"))
    return {
        "product": product,
        "price": price,
        "arrivals": arrivals,
        "payments": payments,
        "loose_advances": loose_advances,
        "debt_left": debt_left,
        "supplier_debt": position.get("we_owe") or Decimal("0"),
        "supplier_advance": position.get("they_owe") or Decimal("0"),
    }


def _money_of(document):
    try:
        return document.money
    except ObjectDoesNotExist:
        return None


def _debt_item(document_id, order):
    if not document_id:
        return None
    return (
        OpenItem.objects.filter(
            document_id=document_id,
            order=order,
            side=OpenItem.Side.WE_OWE,
            lane=OpenItem.Lane.PAYABLE,
        )
        .order_by("pk")
        .first()
    )


def _payment_rows(order, by_document):
    grouped = {}
    allocations = (
        Allocation.objects.filter(
            we_owe__order=order,
            reversal_of__isnull=True,
            reversal__isnull=True,
        )
        .select_related("we_owe__document", "they_owe__document__money")
        .order_by("effective_date", "pk")
    )
    for allocation in allocations:
        row = grouped.get(allocation.they_owe_id)
        if row is None:
            try:
                money = allocation.they_owe.document.money
            except ObjectDoesNotExist:
                money = None
            row = {
                "item": allocation.they_owe,
                "document": allocation.they_owe.document,
                "money": money,
                "applied": Decimal("0"),
                "slices": [],
            }
            grouped[allocation.they_owe_id] = row
        shipment = by_document.get(allocation.we_owe.document_id)
        row["applied"] += allocation.amount
        row["slices"].append(
            {
                "amount": allocation.amount,
                "number": allocation.we_owe.document.number,
                "shipment": shipment,
            }
        )
    rows = []
    for row in grouped.values():
        row["left"] = item_remaining(row["item"])
        row["amount"] = row["item"].amount
        row["date"] = row["document"].effective_date
        rows.append(row)
    rows.sort(key=lambda row: (row["date"], row["document"].pk))
    return rows


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
