from django.contrib.auth.views import LoginView
from django.shortcuts import render

from apps.ui.forms import WorkplaceAuthenticationForm
from apps.ui.http import erp_page
from apps.ui.queries import dashboard_context


class WorkplaceLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = WorkplaceAuthenticationForm
    redirect_authenticated_user = True


@erp_page
def dashboard(request):
    return render(request, "ui/dashboard.html", dashboard_context())
