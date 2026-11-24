import re
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render


def remove_or_disable(request, obj, *, name, back, detail=None):
    """Delete a directory row. A row that documents already use is never deleted and never
    switched off silently: the user sees the reason and decides about «Отключить»."""
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction
    from django.db.models.deletion import ProtectedError, RestrictedError
    from django.shortcuts import redirect

    try:
        with transaction.atomic():
            obj.delete()
    except (ProtectedError, RestrictedError, IntegrityError):
        hint = " Если запись больше не нужна, нажмите «Отключить» — она пропадёт из списков выбора." if hasattr(obj, "active") else ""
        messages.error(request, f"«{name}» уже есть в документах, поэтому удалить нельзя.{hint}")
        return redirect(*detail) if detail else redirect(back)
    except ValidationError as exc:
        messages.error(request, error_text(exc))
        return redirect(*detail) if detail else redirect(back)
    messages.success(request, f"«{name}» удалён.")
    return redirect(back)


def toggle_active(request, obj, *, on_text, off_text):
    """Switch a directory row on or off. Rows that still hold goods, money or debt stay on."""
    from django.contrib import messages
    from django.core.exceptions import ValidationError

    from apps.ui.guards import disable_blocker

    if obj.active:
        reason = disable_blocker(obj)
        if reason:
            messages.error(request, reason)
            return False
    obj.active = not obj.active
    try:
        obj.save()
    except ValidationError as exc:
        messages.error(request, error_text(exc))
        return False
    messages.success(request, on_text if obj.active else off_text)
    return True


CONSTRAINT_TEXT = {
    "product_package": "Масса должна быть больше нуля.",
    "unit_weight_positive": "Масса должна быть больше нуля.",
    "bag_weight_positive": "Для товара в мешках укажите, сколько килограммов в одном мешке.",
    "kg_weight_is_one": "Для товара в килограммах масса единицы всегда 1 кг.",
    "specification_in_contract": "Спецификация с таким номером уже есть в этом договоре.",
    "contract_supplier_number": "У этого поставщика уже есть договор с таким номером.",
    "station_code_unique": "Станция с таким кодом уже есть.",
    "wagon_number_in_shipment": "Номер вагона повторяется в поставке.",
    "wagon_weight_positive": "Вес вагона должен быть больше нуля.",
    "shipment_qty": "Вес поставки должен быть больше нуля.",
    "purchase_qty": "Количество должно быть больше нуля.",
    "purchase_price": "Цена должна быть больше нуля.",
    "purchase_tolerance": "Допуск не может быть отрицательным.",
    "party_has_role": "Отметьте поставщика, покупателя или сотрудника.",
    "overdraft_nonnegative": "Допустимый минус не может быть отрицательным.",
    "location_name": "Такое место уже есть на этом складе.",
    "contract_dates": "Дата окончания не может быть раньше даты договора.",
    "contract_volume_positive": "Объём договора должен быть больше нуля.",
    "contract_limit_positive": "Лимит суммы должен быть больше нуля.",
    "contract_prepayment_range": "Предоплата указывается от 0 до 100 %.",
}

_CONSTRAINT = re.compile(r"(?:Нарушено ограничение|Constraint)\s*[«\"“]?([\w-]+)[»\"”]?(?:\s*is violated)?\.?")
_UNIQUE = re.compile(r"^(.+?) с таким (.+?) уже существует\.?$")


def friendly(text):
    """Turn database wording into plain Russian. Empty string means 'nothing new to say'."""
    text = str(text or "").strip()
    if not text:
        return ""
    unique = _UNIQUE.match(text)
    if unique:
        return f"Значение поля «{unique.group(2).lower()}» уже используется. Укажите другое."
    found = _CONSTRAINT.findall(text)
    if not found:
        return text
    rest = _CONSTRAINT.sub("", text).strip()
    if rest:
        return rest
    known = [CONSTRAINT_TEXT[name] for name in found if name in CONSTRAINT_TEXT]
    if known:
        return " ".join(dict.fromkeys(known))
    return "Данные не прошли проверку. Проверьте заполненные поля."


def error_text(exc):
    if hasattr(exc, "message_dict"):
        parts = [message for messages in exc.message_dict.values() for message in messages]
    elif hasattr(exc, "messages"):
        parts = list(exc.messages)
    else:
        parts = [str(exc)]
    cleaned = [friendly(part) for part in parts]
    cleaned = list(dict.fromkeys(part for part in cleaned if part))
    return " ".join(cleaned) or "Данные не прошли проверку."


def cancel_request(request):
    """Read date and reason of a document cancellation. Returns (None, "") after adding an error message."""
    from datetime import date

    from django.contrib import messages
    from django.utils import timezone

    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, "Укажите причину отмены.")
        return None, ""
    when = request.POST.get("effective_date") or ""
    if not when:
        return timezone.localdate(), note
    try:
        return date.fromisoformat(when), note
    except ValueError:
        messages.error(request, "Укажите дату отмены.")
        return None, ""


def show_cancelled(request):
    return request.GET.get("cancelled") == "1"


def without_cancelled(queryset, prefix="document"):
    """Hide cancelled documents and the technical reversal documents behind them."""
    return queryset.exclude(**{f"{prefix}__kind": "REVERSAL"}).filter(**{f"{prefix}__reversal__isnull": True})


def erp_page(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        from apps.ui.access import user_can_use_erp

        if not user_can_use_erp(request.user):
            return render(request, "ui/forbidden.html", status=403)
        return view(request, *args, **kwargs)

    return wrapped


def remember_list(request, key):
    if request.method == "GET":
        request.session[f"back:{key}"] = request.get_full_path()


def stored_back(request, key, fallback):
    return request.session.get(f"back:{key}") or fallback


def pager(request, queryset, per_page=25):
    page = Paginator(queryset, per_page).get_page(request.GET.get("page") or 1)
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()
