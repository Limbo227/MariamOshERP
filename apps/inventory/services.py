import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import AuditEvent, OperationKey, WarehouseGrant
from apps.inventory.models import (
    OpeningBalance,
    OpeningLine,
    StockLedgerEntry,
    StockPostingSource,
    StorageLocation,
    Warehouse,
)

OPENING_COMMAND = "inventory.opening.post"


@dataclass(frozen=True)
class DraftLine:
    product_id: int
    location_id: int
    quantity: Decimal
    bags: int | None
    basis: str


def stock_totals(company, warehouses):
    return (
        StockLedgerEntry.objects.filter(company=company, location__warehouse__in=warehouses)
        .values("location__warehouse__name", "location__name", "product__name", "product__sku", "product__unit")
        .annotate(quantity=Sum("quantity"), bags=Sum("bags"))
        .order_by("location__warehouse__name", "location__name", "product__name")
    )


def fingerprint_lines(document, lines=None):
    if lines is None:
        lines = document.lines.all()
    ordered = sorted(lines, key=lambda line: (line.product_id, line.location_id, line.pk or 0))
    payload = {
        "company": document.company_id,
        "warehouse": document.warehouse_id,
        "reference": document.reference,
        "effective_date": document.effective_date.isoformat(),
        "lines": [
            {
                "product": line.product_id,
                "location": line.location_id,
                "quantity": format(line.quantity.quantize(Decimal("0.001")), "f"),
                "bags": line.bags,
                "basis": line.basis,
            }
            for line in ordered
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _require_opening_grant(membership, warehouse):
    if not membership.allows("inventory.add_openingbalance"):
        raise PermissionDenied
    if warehouse.company_id != membership.company_id:
        raise PermissionDenied
    if not WarehouseGrant.objects.filter(membership=membership, warehouse=warehouse).exists():
        raise PermissionDenied


@transaction.atomic
def create_draft(*, membership, actor, warehouse_id, reference, effective_date, lines, key=None):
    if actor.pk != membership.user_id:
        raise PermissionDenied
    if not lines:
        raise ValidationError("Добавьте хотя бы одну строку.")
    warehouse = Warehouse.objects.select_for_update().get(pk=warehouse_id)
    _require_opening_grant(membership, warehouse)
    document = OpeningBalance(
        company=membership.company,
        warehouse=warehouse,
        key=key or uuid.uuid4(),
        fingerprint="",
        reference=reference.strip(),
        effective_date=effective_date,
        actor=actor,
        state=OpeningBalance.State.DRAFT,
    )
    document.save()
    saved = []
    for item in lines:
        try:
            product = Product.objects.get(pk=item.product_id, company=membership.company)
            location = StorageLocation.objects.get(pk=item.location_id, warehouse__company=membership.company)
        except (Product.DoesNotExist, StorageLocation.DoesNotExist) as exc:
            raise ValidationError("Товар и место хранения должны относиться к этому предприятию.") from exc
        line = OpeningLine(
            document=document,
            product=product,
            location=location,
            quantity=item.quantity,
            bags=item.bags,
            basis=item.basis,
        )
        try:
            line.save()
        except ValidationError as exc:
            raise ValidationError(f"{product.name}: {'; '.join(exc.messages)}") from exc
        saved.append(line)
    document.fingerprint = fingerprint_lines(document, saved)
    document.save(update_fields=["fingerprint"])
    return document


@transaction.atomic
def post_opening(*, membership, actor, document_id):
    if actor.pk != membership.user_id:
        raise PermissionDenied
    document = OpeningBalance.objects.select_for_update().get(pk=document_id)
    _require_opening_grant(membership, document.warehouse)
    return _post_locked(document, actor)


def _post_locked(document, actor):
    # Opening stock only increases quantity. Phase 2 movements must also lock
    # the company, location and product before they can subtract.
    lines = list(document.lines.select_related("product", "location", "location__warehouse", "document"))
    if not lines:
        raise ValidationError("В документе нет строк.")
    fingerprint = fingerprint_lines(document, lines)
    existing = OperationKey.objects.filter(company=document.company, key=document.key).first()
    if existing is not None:
        same_post = existing.command == OPENING_COMMAND and existing.fingerprint == fingerprint and document.state == OpeningBalance.State.POSTED
        if same_post:
            return document
        raise ValidationError("Этот ключ операции уже использован с другими данными.")
    if document.state != OpeningBalance.State.DRAFT:
        raise ValidationError("Провести можно только черновик.")
    for line in lines:
        try:
            line.full_clean()
        except ValidationError as exc:
            raise ValidationError(f"{line.product.name}: {'; '.join(exc.messages)}") from exc
        source = StockPostingSource(opening_line=line)
        source.save()
        StockLedgerEntry.objects.create(
            source=source,
            effect=StockLedgerEntry.Effect.OPENING,
            company=document.company,
            location=line.location,
            product=line.product,
            quantity=line.quantity,
            bags=line.bags,
            basis=line.basis,
            effective_date=document.effective_date,
            actor=actor,
        )
    document.fingerprint = fingerprint
    document.state = OpeningBalance.State.POSTED
    document.posted_at = timezone.now()
    document.save()
    OperationKey.objects.create(
        company=document.company,
        actor=actor,
        command=OPENING_COMMAND,
        key=document.key,
        fingerprint=fingerprint,
        result_label=f"opening:{document.pk}",
    )
    AuditEvent.objects.create(
        company=document.company,
        actor=actor,
        action=OPENING_COMMAND,
        object_label=document.reference[:160],
        detail=f"Строк: {len(lines)}. Дата: {document.effective_date.isoformat()}.",
    )
    return document
