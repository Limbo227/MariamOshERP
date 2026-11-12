from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import Document, Party
from apps.core.services import commercial_lines, draft_document, post_document, require_active
from apps.finance.models import OpenItem
from apps.finance.services import add_open_item
from apps.sales.models import Sale, SaleLine


@transaction.atomic
def record_sale(*, customer, effective_date, lines, note="", actor=None):
    require_active(customer)
    Party.objects.select_for_update().get(pk=customer.pk)
    prepared = commercial_lines(lines)
    document = draft_document(Document.Kind.SALE, effective_date, note, actor)
    sale = Sale.objects.create(document=document, customer=customer)
    total = Decimal("0")
    for product, quantity, price, bags, amount in prepared:
        SaleLine.objects.create(sale=sale, product=product, quantity=quantity, price=price, amount=amount, bags=bags)
        total += amount
    add_open_item(document, customer, OpenItem.Side.THEY_OWE, OpenItem.Lane.RECEIVABLE, total, f"Продажа {document.number}")
    post_document(
        document,
        snapshot={
            "customer": customer.name,
            "lines": [
                {"product": product.sku, "quantity": quantity, "price": price, "amount": amount}
                for product, quantity, price, _bags, amount in prepared
            ],
            "total": total,
        },
    )
    return sale


@transaction.atomic
def repost_sale(sale, *, actor=None):
    document = Document.objects.select_for_update().get(pk=sale.document_id)
    if document.state != Document.State.DRAFT:
        raise ValidationError("Повторно провести можно только черновик продажи.")
    if document.open_items.exists():
        raise ValidationError("У черновика уже есть долг.")
    total = sum((line.amount for line in sale.lines.all()), Decimal("0"))
    if total <= 0:
        raise ValidationError("В продаже нет суммы.")
    add_open_item(
        document,
        sale.customer,
        OpenItem.Side.THEY_OWE,
        OpenItem.Lane.RECEIVABLE,
        total,
        f"Продажа {document.number}",
    )
    post_document(document, snapshot={"repost": True, "total": total})
    return sale
