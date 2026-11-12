from apps.ui.access import user_can_use_erp


def workspace(request):
    user = getattr(request, "user", None)
    return {"can_use_erp": user_can_use_erp(user) if user is not None else False}
