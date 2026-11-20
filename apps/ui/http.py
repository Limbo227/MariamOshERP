from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render


def remove_or_disable(request, obj, *, name, back):
    """Delete a directory row. If documents still point at it, switch it off instead."""
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.db.models.deletion import ProtectedError
    from django.shortcuts import redirect

    try:
        obj.delete()
    except ProtectedError:
        if not hasattr(obj, "active"):
            messages.error(request, f"«{name}» используется. Удалить её нельзя.")
            return redirect(back)
        obj.active = False
        try:
            obj.save(update_fields=["active"])
        except ValidationError as exc:
            messages.error(request, error_text(exc))
            return redirect(back)
        messages.warning(
            request,
            f"«{name}» уже используется, поэтому запись отключена. История документов сохранена.",
        )
    else:
        messages.success(request, f"«{name}» удалён.")
    return redirect(back)


def error_text(exc):
    if hasattr(exc, "message_dict"):
        parts = [message for messages in exc.message_dict.values() for message in messages]
        if parts:
            return " ".join(parts)
    if hasattr(exc, "messages"):
        return " ".join(exc.messages)
    return str(exc)


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
