import hashlib
import json
import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.operations import existing_operation, finish_operation
from apps.inventory.models import (
    AdjustmentLine,
    GoodsReceipt,
    InventoryLot,
    ReceiptLine,
    StockAdjustment,
    StockLedgerEntry,
    StockPostingSource,
    Warehouse,
)
from apps.procurement.models import CustomsAcceptance, PurchaseOrder

RECEIPT_COMMAND = "inventory.receipt.post"
ADJUSTMENT_COMMAND = "inventory.adjustment.post"
QTY = Decimal("0.001")


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def receipt_fingerprint(receipt):
    payload = {
        "supplier": receipt.supplier_id,
        "order": receipt.order_id,
        "warehouse": receipt.warehouse_id,
        "date": receipt.effective_date.isoformat(),
        "lines": [
            {
                "product": line.product_id,
                "location": line.location_id,
                "order_line": line.order_line_id,
                "wagon": line.transport_unit_id,
                "quantity": format(line.quantity.quantize(QTY), "f"),
                "basis": line.basis,
            }
            for line in receipt.lines.order_by("pk")
        ],
    }
    return _digest(payload)


def assert_timeline(*, location_id, product_id, effective_date, delta):
    rows = list(
        StockLedgerEntry.objects.select_for_update()
        .filter(location_id=location_id, product_id=product_id)
        .order_by("effective_date", "pk")
        .values_list("effective_date", "quantity", "pk")
    )
    rows.append((effective_date, delta, None))
    rows.sort(key=lambda item: (item[0], item[2] or 10**12))
    running = Decimal("0")
    blocked = []
    for row_date, quantity, row_id in rows:
        running += quantity
        if running < 0:
            label = "новая запись" if row_id is None else f"запись #{row_id}"
            blocked.append(f"{label} от {row_date:%d.%m.%Y}")
    if running < 0 or blocked:
        detail = ", ".join(blocked) if blocked else "итоговый остаток"
        raise ValidationError(f"Корректировка создаёт отрицательный остаток: {detail}.")


def _refresh_exception(*, order, receipt, actor):
    from apps.quality.models import ExceptionRecord

    parts = []
    for line in order.lines.all():
        received = ReceiptLine.objects.filter(order_line=line, document__state=GoodsReceipt.State.POSTED).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        if received != line.quantity:
            parts.append(f"{line.product.name}: заказ {line.quantity}, принято {received}")
    record = ExceptionRecord.objects.filter(company=order.company, order=order).first()
    if not parts:
        if record is not None and record.state == ExceptionRecord.State.OPEN:
            record.state = ExceptionRecord.State.RESOLVED
            record.save(update_fields=["state"])
        return
    summary = "; ".join(parts)
    if record is None:
        ExceptionRecord.objects.create(company=order.company, order=order, receipt=receipt, summary=summary, actor=actor)
    elif record.state == ExceptionRecord.State.OPEN:
        record.summary = summary
        record.receipt = receipt
        record.save(update_fields=["summary", "receipt"])


@transaction.atomic
def create_receipt(*, membership, actor, supplier, warehouse, reference, effective_date, lines, order_id=None, customs_acceptance_id=None, key=None):
    if actor.pk != membership.user_id or not membership.allows("inventory.add_goodsreceipt"):
        raise PermissionDenied
    if warehouse.company_id != membership.company_id or warehouse.kind != Warehouse.Kind.RAW:
        raise ValidationError("Приход записывается только на склад сырья.")
    if not lines:
        raise ValidationError("Добавьте хотя бы одну строку.")
    if key is not None:
        existing = GoodsReceipt.objects.filter(company=membership.company, key=key).first()
        if existing is not None:
            return existing
    order = None
    if order_id:
        order = PurchaseOrder.objects.get(pk=order_id, company=membership.company)
        if order.state != PurchaseOrder.State.CONFIRMED:
            raise ValidationError("Приход можно связать только с отправленным заказом.")
        if order.supplier_id != supplier.pk:
            raise ValidationError("Поставщик прихода и заказа не совпадает.")
        if customs_acceptance_id:
            acceptance = CustomsAcceptance.objects.get(pk=customs_acceptance_id, order=order)
        else:
            found = list(CustomsAcceptance.objects.filter(order=order))
            if len(found) == 1:
                acceptance = found[0]
            elif not found:
                raise ValidationError("Сначала таможня отмечает прибытие.")
            else:
                raise ValidationError("Выберите таможенную отметку.")
    else:
        acceptance = None
    receipt = GoodsReceipt.objects.create(
        company=membership.company,
        supplier=supplier,
        order=order,
        customs_acceptance=acceptance,
        warehouse=warehouse,
        key=key or uuid.uuid4(),
        reference=reference.strip(),
        effective_date=effective_date,
        actor=actor,
    )
    for item in lines:
        product = Product.objects.get(pk=item["product_id"], company=membership.company)
        line = ReceiptLine(
            document=receipt,
            product=product,
            location_id=item["location_id"],
            order_line_id=item.get("order_line_id"),
            transport_unit_id=item.get("transport_unit_id"),
            quantity=item["quantity"],
            bags=item.get("bags"),
            basis=item["basis"],
        )
        try:
            line.save()
        except ValidationError as exc:
            raise ValidationError(f"{product.name}: {'; '.join(exc.messages)}") from exc
        if product.kind == Product.Kind.WHEAT:
            batch = item.get("batch_reference") or (order.batch_number if order is not None else "")
            InventoryLot.objects.create(receipt_line=line, company=membership.company, product=product, batch_reference=batch)
    receipt.fingerprint = receipt_fingerprint(receipt)
    receipt.save(update_fields=["fingerprint"])
    return receipt


@transaction.atomic
def post_receipt(*, membership, actor, receipt_id):
    if actor.pk != membership.user_id or not membership.allows("inventory.add_goodsreceipt"):
        raise PermissionDenied
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt_id, company=membership.company)
    fingerprint = receipt_fingerprint(receipt)
    if existing_operation(
        company=receipt.company,
        key=receipt.key,
        command=RECEIPT_COMMAND,
        fingerprint=fingerprint,
        already_posted=receipt.state == GoodsReceipt.State.POSTED,
    ):
        return receipt
    lines = list(receipt.lines.select_related("product", "location"))
    if not lines:
        raise ValidationError("В приходе нет строк.")
    for line in lines:
        if line.product.kind == Product.Kind.WHEAT and not hasattr(line, "lot"):
            raise ValidationError("Для пшеницы нужна входящая партия.")
        StockLedgerEntry.objects.select_for_update().filter(location=line.location, product=line.product).exists()
        source = StockPostingSource.objects.create(receipt_line=line)
        StockLedgerEntry.objects.create(
            source=source,
            effect=StockLedgerEntry.Effect.RECEIPT,
            company=receipt.company,
            location=line.location,
            product=line.product,
            quantity=line.quantity,
            bags=line.bags,
            basis=line.basis,
            effective_date=receipt.effective_date,
            actor=actor,
        )
    receipt.state = GoodsReceipt.State.POSTED
    receipt.posted_at = timezone.now()
    receipt.fingerprint = fingerprint
    receipt.save()
    if receipt.order_id:
        _refresh_exception(order=receipt.order, receipt=receipt, actor=actor)
    finish_operation(
        company=receipt.company,
        actor=actor,
        command=RECEIPT_COMMAND,
        key=receipt.key,
        fingerprint=fingerprint,
        result_label=receipt.reference,
        detail=f"Приход {len(lines)} строк.",
    )
    return receipt


@transaction.atomic
def post_adjustment(*, membership, actor, warehouse, reason, effective_date, lines, key):
    if actor.pk != membership.user_id or not membership.allows("inventory.add_stockadjustment"):
        raise PermissionDenied
    payload = {
        "warehouse": warehouse.pk,
        "date": effective_date.isoformat(),
        "reason": reason,
        "lines": [
            {"product": item["product_id"], "location": item["location_id"], "quantity": format(Decimal(item["quantity"]).quantize(QTY), "f")}
            for item in lines
        ],
    }
    fingerprint = _digest(payload)
    if existing_operation(
        company=membership.company,
        key=key,
        command=ADJUSTMENT_COMMAND,
        fingerprint=fingerprint,
        already_posted=StockAdjustment.objects.filter(company=membership.company, key=key, state=StockAdjustment.State.POSTED).exists(),
    ):
        return StockAdjustment.objects.get(company=membership.company, key=key)
    document = StockAdjustment.objects.create(
        company=membership.company,
        warehouse=warehouse,
        key=key,
        fingerprint=fingerprint,
        reason=reason,
        effective_date=effective_date,
        actor=actor,
    )
    for item in lines:
        product = Product.objects.get(pk=item["product_id"], company=membership.company)
        line = AdjustmentLine(
            document=document,
            product=product,
            location_id=item["location_id"],
            quantity=Decimal(item["quantity"]),
            basis=item["basis"],
            corrects_id=item.get("corrects_id"),
        )
        line.save()
        assert_timeline(location_id=line.location_id, product_id=line.product_id, effective_date=effective_date, delta=line.quantity)
        source = StockPostingSource.objects.create(adjustment_line=line)
        StockLedgerEntry.objects.create(
            source=source,
            effect=StockLedgerEntry.Effect.ADJUSTMENT,
            company=membership.company,
            location=line.location,
            product=line.product,
            quantity=line.quantity,
            basis=line.basis,
            effective_date=effective_date,
            actor=actor,
        )
    document.state = StockAdjustment.State.POSTED
    document.posted_at = timezone.now()
    document.save()
    finish_operation(
        company=membership.company,
        actor=actor,
        command=ADJUSTMENT_COMMAND,
        key=key,
        fingerprint=fingerprint,
        result_label=reason,
        detail=f"Корректировка {len(lines)} строк.",
    )
    return document
