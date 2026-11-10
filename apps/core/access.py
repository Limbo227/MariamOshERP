from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
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


def scoped(*permissions):
    required = permissions or ("core.view_workspace",)

    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            membership = membership_for(request)
            if membership is None or any(not membership.allows(item) for item in required):
                raise PermissionDenied
            request.membership = membership
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def warehouses_for(membership):
    return membership.company.warehouse_set.filter(warehousegrant__membership=membership)


def ensure_group(name, permission_labels):
    group, _created = Group.objects.get_or_create(name=name)
    permissions = []
    for label in permission_labels:
        app_label, codename = label.split(".")
        permissions.append(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    group.permissions.set(permissions)
    return group
