from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.access import scoped
from apps.quality.models import ExceptionRecord


@scoped("core.view_workspace", "quality.view_exceptionrecord")
def exception_list(request):
    records = ExceptionRecord.objects.filter(company=request.membership.company).select_related("order")
    return render(request, "quality/exception_list.html", {"page": Paginator(records, 50).get_page(request.GET.get("page"))})


@scoped("core.view_workspace", "quality.view_exceptionrecord")
@require_POST
def exception_resolve(request, pk):
    record = get_object_or_404(ExceptionRecord, pk=pk, company=request.membership.company)
    record.state = ExceptionRecord.State.RESOLVED
    record.save(update_fields=["state"])
    return redirect("exception_list")
