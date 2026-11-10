from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.access import scoped, warehouses_for
from apps.inventory.forms import OpeningHeaderForm, OpeningLineFormSet
from apps.inventory.models import OpeningBalance
from apps.inventory.services import DraftLine, create_draft, post_opening, stock_totals


def _granted_document(membership, pk):
    return get_object_or_404(
        OpeningBalance.objects.filter(company=membership.company, warehouse__in=warehouses_for(membership)).select_related("warehouse", "actor"),
        pk=pk,
    )


@scoped("core.view_workspace", "inventory.view_warehouse")
def warehouse_list(request):
    warehouses = warehouses_for(request.membership).prefetch_related("storagelocation_set")
    return render(request, "inventory/warehouse_list.html", {"warehouses": warehouses})


@scoped("core.view_workspace", "inventory.view_stockledgerentry")
def balance_list(request):
    totals = stock_totals(request.membership.company, warehouses_for(request.membership))
    return render(request, "inventory/balance_list.html", {"totals": totals})


@scoped("core.view_workspace", "inventory.view_openingbalance")
def opening_list(request):
    documents = OpeningBalance.objects.filter(
        company=request.membership.company,
        warehouse__in=warehouses_for(request.membership),
    ).select_related("warehouse", "actor")
    page = Paginator(documents, 50).get_page(request.GET.get("page"))
    return render(request, "inventory/opening_list.html", {"page": page})


@scoped("core.view_workspace", "inventory.view_openingbalance")
def opening_detail(request, pk):
    document = _granted_document(request.membership, pk)
    lines = document.lines.select_related("product", "location")
    return render(request, "inventory/opening_detail.html", {"document": document, "lines": lines})


@scoped("core.view_workspace", "inventory.add_openingbalance")
def opening_create(request):
    membership = request.membership
    warehouses = warehouses_for(membership)
    requested = request.POST.get("warehouse") if request.method == "POST" else request.GET.get("warehouse")
    warehouse = None
    if requested:
        warehouse = warehouses.filter(pk=requested).first()
        if warehouse is None:
            raise PermissionDenied
    header = OpeningHeaderForm(request.POST or None, initial={"effective_date": timezone.localdate()})
    formset = None
    if warehouse is not None:
        formset = OpeningLineFormSet(
            request.POST or None,
            prefix="lines",
            form_kwargs={"company": membership.company, "warehouse": warehouse},
        )
    if request.method == "POST" and warehouse is not None and header.is_valid() and formset.is_valid():
        lines = [
            DraftLine(
                product_id=row["product"].pk,
                location_id=row["location"].pk,
                quantity=row["quantity"],
                bags=row["bags"],
                basis=row["basis"],
            )
            for row in formset.cleaned_data
            if row
        ]
        try:
            document = create_draft(
                membership=membership,
                actor=request.user,
                warehouse_id=warehouse.pk,
                reference=header.cleaned_data["reference"],
                effective_date=header.cleaned_data["effective_date"],
                lines=lines,
            )
        except ValidationError as exc:
            header.add_error(None, " ".join(exc.messages))
        else:
            messages.success(request, "Черновик сохранён.")
            return redirect("opening_detail", pk=document.pk)
    return render(
        request,
        "inventory/opening_form.html",
        {"warehouses": warehouses, "warehouse": warehouse, "header": header, "formset": formset},
    )


@scoped("core.view_workspace", "inventory.add_openingbalance")
@require_POST
def opening_post(request, pk):
    document = _granted_document(request.membership, pk)
    try:
        post_opening(membership=request.membership, actor=request.user, document_id=document.pk)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Начальные остатки проведены.")
    return redirect("opening_detail", pk=document.pk)
