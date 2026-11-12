"""Procurement progress and cost breakdowns.

Amounts stay in their original currencies. A KGS landed cost is returned only
when every component is already in KGS. No exchange rate is assumed.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.core.models import Document
from apps.core.quantities import MONEY, line_amount, q_qty
from apps.finance.models import CashOperation, MoneyDocument, OpenItem
from apps.inventory.models import ReceiptLine
from apps.procurement.models import PurchaseOrder, Shipment
from apps.procurement.services import receipt_quantity, specification_line


def _posted_expenses():
    return MoneyDocument.objects.filter(
        document__state=Document.State.POSTED,
        document__reversal__isnull=True,
        operation__effect__in=[CashOperation.Effect.PAY_EXPENSE, CashOperation.Effect.SHIPMENT_EXPENSE],
    )


def _by_currency(documents):
    rows = (
        documents.values("account__currency")
        .annotate(total=Sum("amount"))
        .order_by("account__currency")
    )
    return [
        {"currency": row["account__currency"], "amount": (row["total"] or Decimal("0")).quantize(MONEY)}
        for row in rows
        if row["total"]
    ]


def _per_kg(amount, weight):
    if amount is None or not weight:
        return None
    return (amount / weight).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def received_quantity(order):
    total = ReceiptLine.objects.filter(
        purchase_line__order=order,
        receipt__document__state=Document.State.POSTED,
        receipt__document__reversal__isnull=True,
    ).aggregate(total=Sum("quantity"))["total"]
    return total or Decimal("0")


def tolerance_warning(planned, received, tolerance_percent):
    if not planned or tolerance_percent is None:
        return ""
    variance = ((received - planned) / planned * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    limit = Decimal(tolerance_percent).quantize(Decimal("0.01"))
    if limit <= 0:
        return ""
    if variance > limit:
        return "Фактическое количество выше допуска."
    if variance < -limit:
        return "Фактическое количество ниже допуска."
    if variance == limit:
        return "На верхней границе допуска."
    if variance == -limit:
        return "На нижней границе допуска."
    return ""


def specification_progress(order):
    line = order.lines.select_related("product").first()
    planned = line.quantity if line is not None else Decimal("0")
    received = received_quantity(order)
    remaining = planned - received
    percent = None
    if planned:
        percent = (received / planned * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    posted_amount = OpenItem.objects.filter(
        order=order,
        side=OpenItem.Side.WE_OWE,
        lane=OpenItem.Lane.PAYABLE,
        document__state=Document.State.POSTED,
        document__reversal__isnull=True,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    shipment_expenses = _by_currency(_posted_expenses().filter(shipment__order=order))
    unallocated = _by_currency(_posted_expenses().filter(order=order, shipment__isnull=True))
    return {
        "supplier": order.supplier,
        "contract": order.contract,
        "number": order.specification_number,
        "product": line.product if line is not None else None,
        "ordered_quantity": planned,
        "received_quantity": received,
        "remaining_quantity": remaining,
        "received_percent": percent,
        "variance_quantity": received - planned,
        "tolerance_percent": order.tolerance_percent,
        "operational_status": order.operational_status,
        "operational_status_label": order.get_operational_status_display(),
        "shipment_count": order.shipments.count(),
        "posted_shipment_count": order.shipments.filter(status=Shipment.State.POSTED).count(),
        "draft_shipment_count": order.shipments.filter(status=Shipment.State.DRAFT).count(),
        "supplier_amount": posted_amount.quantize(MONEY),
        "currency": order.currency,
        "shipment_expenses": shipment_expenses,
        "unallocated_expenses": unallocated,
        "warning": tolerance_warning(planned, received, order.tolerance_percent),
    }


def shipment_purchase_amount(shipment):
    shipment = Shipment.objects.select_related("order", "receipt__document").get(pk=shipment.pk)
    if shipment.status != Shipment.State.POSTED:
        return Decimal("0.00"), shipment.order.currency
    if shipment.receipt_id:
        item = (
            shipment.receipt.document.open_items.filter(side=OpenItem.Side.WE_OWE, lane=OpenItem.Lane.PAYABLE)
            .order_by("pk")
            .first()
        )
        if item is not None:
            return item.amount, item.currency
    line = specification_line(shipment.order)
    quantity = receipt_quantity(line.product, shipment.quantity)
    return line_amount(quantity, line.price), shipment.order.currency


def shipment_cost(shipment):
    shipment = Shipment.objects.select_related("order", "receipt__document").get(pk=shipment.pk)
    amount, currency = shipment_purchase_amount(shipment)
    weight = q_qty(shipment.quantity)
    expenses = _by_currency(_posted_expenses().filter(shipment=shipment))
    currencies = {currency} | {row["currency"] for row in expenses}
    valued = shipment.status == Shipment.State.POSTED and currencies == {"KGS"}
    expense_total_kgs = sum((row["amount"] for row in expenses if row["currency"] == "KGS"), Decimal("0"))
    purchase_kgs = amount if currency == "KGS" else None
    landed = None
    if valued and purchase_kgs is not None:
        landed = (purchase_kgs + expense_total_kgs).quantize(MONEY)
    return {
        "weight_kg": weight,
        "posted": shipment.status == Shipment.State.POSTED,
        "purchase_currency": currency,
        "purchase_amount": amount,
        "purchase_per_kg": _per_kg(amount, weight),
        "expenses_by_currency": expenses,
        "expenses_per_kg": [
            {"currency": row["currency"], "amount": _per_kg(row["amount"], weight)} for row in expenses
        ],
        "valued_in_kgs": valued,
        "kgs_landed_cost": landed,
        "kgs_landed_cost_per_kg": _per_kg(landed, weight) if landed is not None else None,
        "valuation_note": ""
        if valued
        else "Итог в KGS не рассчитан: нет согласованного правила пересчёта валют.",
    }


def specification_cost(order):
    progress = specification_progress(order)
    return {
        "received_quantity": progress["received_quantity"],
        "supplier_amount": progress["supplier_amount"],
        "currency": progress["currency"],
        "shipment_expenses": progress["shipment_expenses"],
        "unallocated_expenses": progress["unallocated_expenses"],
        "supplier_per_kg": _per_kg(progress["supplier_amount"], progress["received_quantity"]),
        "valued_in_kgs": progress["currency"] == "KGS"
        and all(row["currency"] == "KGS" for row in progress["shipment_expenses"])
        and all(row["currency"] == "KGS" for row in progress["unallocated_expenses"]),
    }


def specification_rows():
    orders = PurchaseOrder.objects.select_related("supplier", "contract", "document").prefetch_related("lines__product")
    return [specification_progress(order) for order in orders]


def shipment_rows():
    rows = []
    shipments = Shipment.objects.select_related(
        "order__supplier",
        "order__contract",
        "order__document",
        "departure_station",
        "receipt__document",
    ).prefetch_related("order__lines__product")
    for shipment in shipments:
        amount, currency = shipment_purchase_amount(shipment)
        line = shipment.order.lines.first()
        rows.append(
            {
                "shipment": shipment,
                "contract": shipment.order.contract,
                "specification": shipment.order,
                "supplier": shipment.order.supplier,
                "station": shipment.departure_station,
                "departure_date": shipment.departure_date,
                "arrival_date": shipment.arrival_date,
                "wagon_count": shipment.wagon_count,
                "weight_kg": shipment.quantity,
                "received_weight_kg": shipment.quantity if shipment.status == Shipment.State.POSTED else Decimal("0"),
                "draft_weight_kg": shipment.quantity if shipment.status == Shipment.State.DRAFT else Decimal("0"),
                "price": line.price if line else None,
                "purchase_amount": amount,
                "currency": currency,
                "expenses": _by_currency(_posted_expenses().filter(shipment=shipment)),
                "status": shipment.status,
                "status_label": shipment.get_status_display(),
            }
        )
    return rows


def supplier_balance_report(party):
    from apps.finance.queries import party_position

    position = party_position(party)
    contracts = {}
    orders = (
        PurchaseOrder.objects.filter(supplier=party)
        .select_related("contract", "document")
        .prefetch_related("lines", "shipments")
    )
    for order in orders:
        key = order.contract_id or 0
        bucket = contracts.setdefault(
            key,
            {"contract": order.contract, "specifications": []},
        )
        progress = specification_progress(order)
        shipments = []
        for shipment in order.shipments.all():
            amount, currency = shipment_purchase_amount(shipment)
            shipments.append(
                {
                    "shipment": shipment,
                    "amount": amount if shipment.status == Shipment.State.POSTED else Decimal("0.00"),
                    "currency": currency,
                    "weight_kg": shipment.quantity,
                    "status": shipment.status,
                }
            )
        bucket["specifications"].append({"progress": progress, "shipments": shipments})
    return {"position": position, "contracts": list(contracts.values())}
