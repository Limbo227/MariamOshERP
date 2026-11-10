import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.operations import existing_operation, finish_operation
from apps.procurement.models import (
    AmendmentLine,
    CustomsAcceptance,
    OrderAmendment,
    OrderLine,
    PurchaseOrder,
    Shipment,
    TransportUnit,
)
from apps.settlements.services import agreed_total, open_order_obligation, post_amendment_delta

CONFIRM_COMMAND = "procurement.order.confirm"


@dataclass(frozen=True)
class OrderLineInput:
    product_id: int
    quantity: Decimal
    unit_price: Decimal | None


def _fingerprint(order, lines):
    payload = {
        "supplier": order.supplier_id,
        "reference": order.reference,
        "date": order.effective_date.isoformat(),
        "lines": [
            {"product": line.product_id, "quantity": format(line.quantity.quantize(Decimal("0.001")), "f"), "price": None if line.unit_price is None else format(line.unit_price, "f")}
            for line in sorted(lines, key=lambda item: item.product_id)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def create_order(*, membership, actor, supplier, reference, effective_date, lines, contract_reference="", batch_number="", wagon_count=None, key=None):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_purchaseorder"):
        raise PermissionDenied
    if supplier.company_id != membership.company_id:
        raise ValidationError("Поставщик относится к другому предприятию.")
    if not lines:
        raise ValidationError("Добавьте хотя бы одну строку.")
    if key is not None:
        existing = PurchaseOrder.objects.filter(company=membership.company, key=key).first()
        if existing is not None:
            stored = [(line.product_id, line.quantity, line.unit_price) for line in existing.lines.order_by("product_id")]
            incoming = sorted((item.product_id, item.quantity, item.unit_price) for item in lines)
            same = (
                existing.supplier_id == supplier.pk
                and existing.reference == reference.strip()
                and existing.effective_date == effective_date
                and existing.batch_number == (batch_number or "").strip()
                and existing.wagon_count == wagon_count
                and stored == incoming
            )
            if not same:
                raise ValidationError("Этот ключ операции уже использован с другими данными.")
            return existing
    order = PurchaseOrder(
        company=membership.company,
        supplier=supplier,
        reference=reference.strip(),
        contract_reference=contract_reference,
        batch_number=(batch_number or "").strip(),
        wagon_count=wagon_count,
        effective_date=effective_date,
        key=key or uuid.uuid4(),
        actor=actor,
    )
    order.save()
    saved = []
    for item in lines:
        product = Product.objects.get(pk=item.product_id, company=membership.company)
        line = OrderLine(order=order, product=product, quantity=item.quantity, unit=product.unit, unit_price=item.unit_price)
        try:
            line.save()
        except ValidationError as exc:
            raise ValidationError(f"{product.name}: {'; '.join(exc.messages)}") from exc
        saved.append(line)
    if any(line.product.kind == Product.Kind.WHEAT for line in saved) and (not order.batch_number or not order.wagon_count):
        raise ValidationError("Для пшеницы нужны партия и число вагонов.")
    order.fingerprint = _fingerprint(order, saved)
    order.save(update_fields=["fingerprint"])
    return order


@transaction.atomic
def confirm_order(*, membership, actor, order_id):
    if actor.pk != membership.user_id or not membership.allows("procurement.confirm_purchaseorder"):
        raise PermissionDenied
    order = PurchaseOrder.objects.select_for_update().get(pk=order_id, company=membership.company)
    lines = list(order.lines.select_related("product"))
    fingerprint = _fingerprint(order, lines)
    if existing_operation(company=order.company, key=order.key, command=CONFIRM_COMMAND, fingerprint=fingerprint, already_posted=order.state == PurchaseOrder.State.CONFIRMED):
        return order
    if order.state != PurchaseOrder.State.DRAFT:
        raise ValidationError("Отправить можно только заявку.")
    if not lines:
        raise ValidationError("В заказе нет строк.")
    if any(line.product.kind == Product.Kind.WHEAT for line in lines) and (not order.batch_number or not order.wagon_count):
        raise ValidationError("Для пшеницы нужны партия и число вагонов.")
    for line in lines:
        if line.unit_price is None:
            raise ValidationError("Нет согласованной цены.")
    order.fingerprint = fingerprint
    order.state = PurchaseOrder.State.CONFIRMED
    order.confirmed_by = actor
    order.confirmed_at = timezone.now()
    order.save()
    open_order_obligation(order=order, actor=actor)
    finish_operation(
        company=order.company,
        actor=actor,
        command=CONFIRM_COMMAND,
        key=order.key,
        fingerprint=fingerprint,
        result_label=order.reference,
        detail=f"Долг {agreed_total(order)} KGS.",
    )
    return order


@transaction.atomic
def amend_order(*, membership, actor, order_id, reason, effective_date, terms):
    if actor.pk != membership.user_id or not membership.allows("procurement.amend_purchaseorder"):
        raise PermissionDenied
    order = PurchaseOrder.objects.select_for_update().get(pk=order_id, company=membership.company)
    if order.state != PurchaseOrder.State.CONFIRMED:
        raise ValidationError("Изменять можно только подтверждённый заказ.")
    previous = agreed_total(order)
    revision = (order.amendments.order_by("-revision").values_list("revision", flat=True).first() or 0) + 1
    amendment = OrderAmendment.objects.create(order=order, revision=revision, reason=reason, effective_date=effective_date, actor=actor)
    seen = set()
    for line_id, quantity, price in terms:
        line = order.lines.get(pk=line_id)
        if line.pk in seen:
            raise ValidationError("Строка заказа повторяется.")
        seen.add(line.pk)
        AmendmentLine.objects.create(amendment=amendment, order_line=line, new_quantity=quantity, new_price=price)
    if len(seen) != order.lines.count():
        raise ValidationError("Нужны новые условия по каждой строке.")
    post_amendment_delta(order=order, amendment=amendment, actor=actor, previous_total=previous)
    return amendment


@transaction.atomic
def accept_at_customs(*, membership, actor, order_id, port, quantity, accepted_on):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_customsacceptance"):
        raise PermissionDenied
    order = PurchaseOrder.objects.select_for_update().get(pk=order_id, company=membership.company)
    if order.state != PurchaseOrder.State.CONFIRMED:
        raise ValidationError("Таможня принимает только отправленный заказ.")
    port = port.strip()
    if not port:
        raise ValidationError("Нужен таможенный пост.")
    if quantity <= 0:
        raise ValidationError("Количество должно быть больше нуля.")
    return CustomsAcceptance.objects.create(order=order, port=port, quantity=quantity, accepted_on=accepted_on, actor=actor)


@transaction.atomic
def create_shipment(*, membership, actor, supplier, reference, customs_port, order_id=None, expected_date=None):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_shipment"):
        raise PermissionDenied
    order = None
    if order_id:
        order = PurchaseOrder.objects.get(pk=order_id, company=membership.company)
    shipment = Shipment(
        company=membership.company,
        supplier=supplier,
        order=order,
        reference=reference.strip(),
        customs_port=customs_port,
        expected_date=expected_date,
        actor=actor,
    )
    shipment.save()
    return shipment


@transaction.atomic
def add_wagon(*, membership, shipment_id, identifier, declared_quantity, order_line_id=None):
    if not membership.allows("procurement.add_transportunit"):
        raise PermissionDenied
    shipment = Shipment.objects.get(pk=shipment_id, company=membership.company)
    order_line = shipment.order.lines.get(pk=order_line_id) if order_line_id else None
    return TransportUnit.objects.create(
        shipment=shipment,
        identifier=identifier.strip(),
        declared_quantity=declared_quantity,
        order_line=order_line,
    )


def received_quantity(order_line):
    from django.db.models import Sum

    from apps.inventory.models import GoodsReceipt, ReceiptLine

    total = ReceiptLine.objects.filter(order_line=order_line, document__state=GoodsReceipt.State.POSTED).aggregate(total=Sum("quantity"))["total"]
    return total or Decimal("0")
