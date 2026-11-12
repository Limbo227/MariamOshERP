from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render


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


def pager(request, queryset, per_page=25):
    page = Paginator(queryset, per_page).get_page(request.GET.get("page") or 1)
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()
