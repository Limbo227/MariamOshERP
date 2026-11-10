from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.core.operations import existing_operation, finish_operation
from apps.quality.models import (
    LocalQualityValue,
    QualityInspection,
    ReleaseDecision,
    SupplierQualityValue,
)

RELEASE_COMMAND = "quality.release.record"


def compare_quality(*, shipment, transport_unit=None):
    passport = SupplierQualityValue.objects.filter(shipment=shipment, transport_unit=transport_unit)
    if transport_unit is not None and not passport.exists():
        passport = SupplierQualityValue.objects.filter(shipment=shipment, transport_unit__isnull=True)
    inspection = None
    if transport_unit is not None:
        inspection = QualityInspection.objects.filter(transport_unit=transport_unit).order_by("-pk").first()
        if inspection is None:
            inspection = QualityInspection.objects.filter(receipt_line__transport_unit=transport_unit).order_by("-pk").first()
    local_rows = inspection.values.all() if inspection else LocalQualityValue.objects.none()
    local_by_key = {(row.parameter, row.unit): row for row in local_rows}
    rows = []
    for item in passport:
        local = local_by_key.get((item.parameter, item.unit))
        rows.append(
            {
                "parameter": item.parameter,
                "unit": item.unit,
                "passport": item.number if item.number is not None else item.text,
                "local": None if local is None else (local.number if local.number is not None else local.text),
            }
        )
    return rows


@transaction.atomic
def release_quantity(*, membership, actor, receipt_line, quantity, reason, released_on, key):
    if actor.pk != membership.user_id or not membership.allows("quality.add_releasedecision"):
        raise PermissionDenied
    quantity = Decimal(quantity)
    fingerprint = f"{receipt_line.pk}:{quantity}:{reason}"
    already = ReleaseDecision.objects.filter(key=key, status=ReleaseDecision.Status.ACTIVE).exists()
    if existing_operation(company=membership.company, key=key, command=RELEASE_COMMAND, fingerprint=fingerprint, already_posted=already):
        return ReleaseDecision.objects.get(key=key)
    if receipt_line.document.company_id != membership.company_id or receipt_line.document.state != receipt_line.document.State.POSTED:
        raise ValidationError("Допуск относится только к проведённому приходу этого предприятия.")
    released = receipt_line.releases.filter(status=ReleaseDecision.Status.ACTIVE).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    if released + quantity > receipt_line.quantity:
        raise ValidationError("Допуск больше принятого количества.")
    decision = ReleaseDecision.objects.create(
        receipt_line=receipt_line,
        quantity=quantity,
        reason=reason,
        actor=actor,
        key=key,
        released_on=released_on,
    )
    finish_operation(
        company=membership.company,
        actor=actor,
        command=RELEASE_COMMAND,
        key=key,
        fingerprint=fingerprint,
        result_label=f"Допуск {quantity}",
        detail=reason,
    )
    return decision


def released_total(receipt_line):
    return receipt_line.releases.filter(status=ReleaseDecision.Status.ACTIVE).aggregate(total=Sum("quantity"))["total"] or Decimal("0")


def pending_quantity(receipt_line):
    return receipt_line.quantity - released_total(receipt_line)
