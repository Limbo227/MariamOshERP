from datetime import date, datetime
from decimal import Decimal

from apps.core.models import AuditEntry


def json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


def write_audit(
    *,
    action,
    document=None,
    actor=None,
    detail="",
    target_type="",
    target_id="",
    number="",
    kind="",
    snapshot=None,
):
    if document is not None:
        number = number or document.number
        kind = kind or document.kind
        document_id = document.pk
    else:
        document_id = None
    return AuditEntry.objects.create(
        action=action,
        document_id=document_id,
        document_number=number or "",
        document_kind=kind or "",
        target_type=target_type or "",
        target_id=str(target_id or ""),
        actor=actor if getattr(actor, "pk", None) else None,
        detail=detail or "",
        snapshot=None if snapshot is None else json_safe(snapshot),
    )
