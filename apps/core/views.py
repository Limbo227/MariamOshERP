from django.contrib.auth import views as auth_views
from django.shortcuts import render

from apps.core.access import scoped, warehouses_for
from apps.inventory.models import OpeningBalance
from apps.inventory.services import stock_totals


class WorkspaceLoginView(auth_views.LoginView):
    template_name = "registration/login.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "w-full rounded-md border border-stone-300 bg-white px-3 py-2"
        return form


@scoped("core.view_workspace")
def dashboard(request):
    membership = request.membership
    warehouses = warehouses_for(membership)
    totals = []
    if membership.allows("inventory.view_stockledgerentry"):
        totals = list(stock_totals(membership.company, warehouses)[:8])
    drafts = []
    if membership.allows("inventory.view_openingbalance"):
        drafts = list(
            OpeningBalance.objects.filter(company=membership.company, warehouse__in=warehouses, state=OpeningBalance.State.DRAFT)
            .select_related("warehouse")[:5]
        )
    return render(request, "core/dashboard.html", {"totals": totals, "drafts": drafts})
