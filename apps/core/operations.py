from django.core.exceptions import ValidationError

from apps.core.models import AuditEvent, OperationKey


def existing_operation(*, company, key, command, fingerprint, already_posted):
    existing = OperationKey.objects.filter(company=company, key=key).first()
    if existing is None:
        return None
    same = existing.command == command and existing.fingerprint == fingerprint and already_posted
    if same:
        return existing
    raise ValidationError("Этот ключ операции уже использован с другими данными.")


def finish_operation(*, company, actor, command, key, fingerprint, result_label, detail):
    OperationKey.objects.create(
        company=company,
        actor=actor,
        command=command,
        key=key,
        fingerprint=fingerprint,
        result_label=result_label,
    )
    AuditEvent.objects.create(company=company, actor=actor, action=command, object_label=result_label[:160], detail=detail)
