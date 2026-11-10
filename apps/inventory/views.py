from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.access import scoped, warehouses_for
from apps.inventory.forms import (
    AdjustmentForm,
    OpeningHeaderForm,
    OpeningLineFormSet,
    ReceiptHeaderForm,
    ReceiptLineFormSet,
)
from apps.inventory.models import GoodsReceipt, OpeningBalance, StockLedgerEntry, Warehouse
from apps.inventory.posting import create_receipt, post_adjustment, post_receipt
from apps.inventory.services import DraftLine, create_draft, post_opening, stock_totals
from apps.quality.forms import LocalQualityForm, ReleaseForm
from apps.quality.models import LocalQualityValue, QualityInspection
from apps.quality.services import pending_quantity, release_quantity


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


@scoped("core.view_workspace", "inventory.view_goodsreceipt")
def receipt_list(request):
    documents = GoodsReceipt.objects.filter(company=request.membership.company, warehouse__in=warehouses_for(request.membership)).select_related("supplier", "warehouse")
    return render(request, "inventory/receipt_list.html", {"page": Paginator(documents, 50).get_page(request.GET.get("page"))})


@scoped("core.view_workspace", "inventory.add_goodsreceipt")
def receipt_create(request):
    membership = request.membership
    warehouses = warehouses_for(membership).filter(kind=Warehouse.Kind.RAW)
    warehouse = warehouses.first()
    header = ReceiptHeaderForm(request.POST or None, company=membership.company, initial={"effective_date": timezone.localdate()})
    formset = ReceiptLineFormSet(request.POST or None, prefix="lines", form_kwargs={"company": membership.company, "warehouse": warehouse}) if warehouse else None
    if request.method == "POST" and warehouse is not None and header.is_valid() and formset.is_valid():
        lines = [
            {
                "product_id": row["product"].pk,
                "location_id": row["location"].pk,
                "quantity": row["quantity"],
                "basis": row["basis"],
                "batch_reference": row.get("batch_reference") or "",
            }
            for row in formset.cleaned_data
            if row
        ]
        try:
            receipt = create_receipt(
                membership=membership,
                actor=request.user,
                supplier=header.cleaned_data["supplier"],
                warehouse=warehouse,
                reference=header.cleaned_data["reference"],
                effective_date=header.cleaned_data["effective_date"],
                lines=lines,
                order_id=header.cleaned_data["order"].pk if header.cleaned_data["order"] else None,
                key=header.cleaned_data["key"],
            )
        except ValidationError as exc:
            header.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("receipt_detail", pk=receipt.pk)
    return render(request, "inventory/receipt_form.html", {"header": header, "formset": formset, "warehouse": warehouse})


@scoped("core.view_workspace", "inventory.view_goodsreceipt")
def receipt_detail(request, pk):
    receipt = get_object_or_404(
        GoodsReceipt.objects.filter(company=request.membership.company, warehouse__in=warehouses_for(request.membership)).select_related("supplier", "warehouse", "order"),
        pk=pk,
    )
    lines = []
    for line in receipt.lines.select_related("product", "location"):
        pending = pending_quantity(line) if receipt.state == GoodsReceipt.State.POSTED else None
        lines.append({"line": line, "pending": pending, "releases": line.releases.all()})
    return render(
        request,
        "inventory/receipt_detail.html",
        {
            "receipt": receipt,
            "lines": lines,
            "can_post": request.membership.allows("inventory.add_goodsreceipt"),
            "can_release": request.membership.allows("quality.add_releasedecision"),
            "can_inspect": request.membership.allows("quality.add_qualityinspection"),
            "release_form": ReleaseForm(initial={"released_on": timezone.localdate()}),
            "quality_form": LocalQualityForm(),
        },
    )


@scoped("core.view_workspace", "inventory.add_goodsreceipt")
@require_POST
def receipt_post(request, pk):
    try:
        post_receipt(membership=request.membership, actor=request.user, receipt_id=pk)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("receipt_detail", pk=pk)


@scoped("core.view_workspace", "quality.add_qualityinspection")
@require_POST
def receipt_inspect(request, pk):
    receipt = get_object_or_404(GoodsReceipt, pk=pk, company=request.membership.company)
    form = LocalQualityForm(request.POST)
    line = receipt.lines.order_by("pk").first()
    if form.is_valid() and line is not None:
        inspection = QualityInspection.objects.create(
            company=request.membership.company,
            receipt_line=line,
            inspected_on=timezone.localdate(),
            inspector=request.user,
            comment=form.cleaned_data["comment"],
        )
        LocalQualityValue.objects.create(
            inspection=inspection,
            parameter=form.cleaned_data["parameter"],
            number=form.cleaned_data["number"],
            unit=form.cleaned_data["unit"],
        )
    return redirect("receipt_detail", pk=pk)


@scoped("core.view_workspace", "quality.add_releasedecision")
@require_POST
def receipt_release(request, pk):
    receipt = get_object_or_404(GoodsReceipt, pk=pk, company=request.membership.company)
    form = ReleaseForm(request.POST)
    line = receipt.lines.filter(pk=request.POST.get("line")).first()
    if form.is_valid() and line is not None:
        try:
            release_quantity(
                membership=request.membership,
                actor=request.user,
                receipt_line=line,
                quantity=form.cleaned_data["quantity"],
                reason=form.cleaned_data["reason"],
                released_on=form.cleaned_data["released_on"],
                key=form.cleaned_data["key"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("receipt_detail", pk=pk)


@scoped("core.view_workspace", "inventory.add_stockadjustment")
def adjustment_create(request):
    membership = request.membership
    warehouse = warehouses_for(membership).filter(kind=Warehouse.Kind.RAW).first()
    form = AdjustmentForm(request.POST or None, company=membership.company, warehouse=warehouse, initial={"effective_date": timezone.localdate()}) if warehouse else None
    if request.method == "POST" and form is not None and form.is_valid():
        try:
            post_adjustment(
                membership=membership,
                actor=request.user,
                warehouse=warehouse,
                reason=form.cleaned_data["reason"],
                effective_date=form.cleaned_data["effective_date"],
                lines=[{"product_id": form.cleaned_data["product"].pk, "location_id": form.cleaned_data["location"].pk, "quantity": form.cleaned_data["quantity"], "basis": form.cleaned_data["basis"]}],
                key=form.cleaned_data["key"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("ledger_list")
    return render(request, "inventory/adjustment_form.html", {"form": form, "warehouse": warehouse})


@scoped("core.view_workspace", "inventory.view_stockledgerentry")
def ledger_list(request):
    entries = StockLedgerEntry.objects.filter(company=request.membership.company, location__warehouse__in=warehouses_for(request.membership)).select_related("product", "location").order_by("-effective_date", "-pk")
    return render(request, "inventory/ledger_list.html", {"page": Paginator(entries, 50).get_page(request.GET.get("page"))})
