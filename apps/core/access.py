from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from apps.core.models import Membership


def membership_for(request):
    if not request.user.is_authenticated:
        return None
    if hasattr(request, "workspace_membership"):
        return request.workspace_membership
    query = Membership.objects.select_related("company", "role").filter(user=request.user)
    selected = request.session.get("company_id")
    membership = query.filter(company_id=selected).first() if selected else query.order_by("pk").first()
    request.workspace_membership = membership
    return membership


def scoped(permission="core.view_workspace"):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            membership = membership_for(request)
            if membership is None or not membership.allows(permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def warehouses_for(membership):
    return membership.company.warehouse_set.filter(warehousegrant__membership=membership)

