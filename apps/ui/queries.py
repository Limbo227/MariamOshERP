from decimal import Decimal

from django.db.models import Count, DecimalField, Exists, Min, OuterRef, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse

from apps.core.models import Document, Organization, Party
from apps.finance.models import CashOperation, MoneyDocument
from apps.finance.queries import supplier_balances
from apps.inventory.models import GoodsReceipt
from apps.inventory.queries import stock_by_unit
from apps.procurement.models import PurchaseOrder, Shipment

PURCHASE_LIMIT = 10
SHIPMENT_LIMIT = 10
OPERATION_LIMIT = 8
INCOMING = (Shipment.Status.DRAFT,)


def _reversed(field="document_id"):
    return Exists(Document.objects.filter(reverses_id=OuterRef(field)))


def dashboard_context():
    balances = supplier_balances()
    status_counts = {
        row["status"]: row["total"] for row in Shipment.objects.values("status").annotate(total=Count("pk"))
    }
    return {
        "organization": Organization.objects.only("legal_name").first(),
        "supplier_count": Party.objects.filter(is_supplier=True, active=True).count(),
        "purchase_count": PurchaseOrder.objects.filter(~_reversed()).count(),
        "shipments_in_transit": status_counts.get(Shipment.Status.DRAFT, 0),
        "shipments_at_customs": 0,
        "shipments_posted": status_counts.get(Shipment.Status.POSTED, 0),
        "shipments_arrived": 0,
        "stock": stock_by_unit(),
        "payables": balances["payable"],
        "advances": balances["advances"],
        "recent_purchases": _recent_purchases(),
        "incoming_shipments": _incoming_shipments(),
        "recent_operations": _recent_operations(),
    }


def _recent_purchases():
    return (
        PurchaseOrder.objects.select_related("document", "supplier", "contract")
        .annotate(
            planned=Coalesce(
                Sum("lines__amount"),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2)),
            ),
            is_reversed=_reversed(),
        )
        .order_by("-document__effective_date", "-pk")[:PURCHASE_LIMIT]
    )


def _incoming_shipments():
    return (
        Shipment.objects.filter(status__in=INCOMING)
        .select_related("order__document", "order__supplier", "order__contract")
        .prefetch_related("wagons")
        .annotate(
            unit=Min("order__lines__product__unit"),
            unit_count=Count("order__lines__product__unit", distinct=True),
        )
        .order_by("-departure_date", "-pk")[:SHIPMENT_LIMIT]
    )


def _recent_operations():
    receipts = (
        GoodsReceipt.objects.select_related("document", "supplier", "warehouse")
        .annotate(
            quantity=Sum("lines__quantity"),
            unit=Min("lines__product__unit"),
            unit_count=Count("lines__product__unit", distinct=True),
            is_reversed=_reversed(),
        )
        .order_by("-document__effective_date", "-pk")[:OPERATION_LIMIT]
    )
    payments = (
        MoneyDocument.objects.filter(operation__effect=CashOperation.Effect.PAY_PARTY)
        .select_related("document", "party", "account")
        .annotate(is_reversed=_reversed())
        .order_by("-document__effective_date", "-pk")[:OPERATION_LIMIT]
    )
    rows = [_receipt_row(receipt) for receipt in receipts]
    rows.extend(_payment_row(payment) for payment in payments)
    rows.sort(key=lambda row: (row["date"], row["posted_at"], row["number"]), reverse=True)
    return rows[:OPERATION_LIMIT]


def _receipt_row(receipt):
    document = receipt.document
    return {
        "date": document.effective_date,
        "posted_at": document.posted_at,
        "kind": "Приёмка",
        "number": document.number,
        "party": receipt.supplier.name,
        "mode": "qty",
        "quantity": receipt.quantity,
        "unit": receipt.unit if receipt.unit_count == 1 else "",
        "mixed": (receipt.unit_count or 0) > 1,
        "amount": None,
        "currency": "",
        "place": receipt.warehouse.name,
        "reversed": receipt.is_reversed,
        "url": reverse("receipt_detail", args=[receipt.pk]),
    }


def _payment_row(payment):
    document = payment.document
    return {
        "date": document.effective_date,
        "posted_at": document.posted_at,
        "kind": "Оплата поставщику",
        "number": document.number,
        "party": payment.party.name if payment.party_id else "—",
        "mode": "money",
        "quantity": None,
        "unit": "",
        "mixed": False,
        "amount": payment.amount,
        "currency": payment.account.currency,
        "place": payment.account.name,
        "reversed": payment.is_reversed,
        "url": reverse("money_detail", args=[payment.pk]),
    }
