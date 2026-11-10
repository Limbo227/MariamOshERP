from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.catalog.forms import CounterpartyForm, ProductForm, StationForm
from apps.catalog.models import OriginStation, Product, Supplier
from apps.core.access import scoped
from apps.procurement.contracts import create_counterparty, create_good, create_station


@scoped("core.view_workspace", "catalog.view_product")
def product_list(request):
    products = Product.objects.filter(company=request.membership.company).select_related("requirement__component")
    page = Paginator(products, 50).get_page(request.GET.get("page"))
    return render(request, "catalog/product_list.html", {"page": page})


@scoped("core.view_workspace", "catalog.add_product")
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_good(
                membership=request.membership,
                actor=request.user,
                name=form.cleaned_data["name"],
                kind=form.cleaned_data["kind"],
                unit=form.cleaned_data["unit"],
                grade=form.cleaned_data["grade"],
                package_kg=form.cleaned_data["package_kg"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("product_list")
    return render(request, "catalog/product_form.html", {"form": form})


@scoped("core.view_workspace", "catalog.view_originstation")
def station_list(request):
    stations = OriginStation.objects.filter(company=request.membership.company, active=True)
    return render(request, "catalog/station_list.html", {"stations": stations})


@scoped("core.view_workspace", "catalog.add_originstation")
def station_create(request):
    form = StationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_station(membership=request.membership, actor=request.user, name=form.cleaned_data["name"])
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("station_list")
    return render(request, "catalog/station_form.html", {"form": form})


@scoped("core.view_workspace", "catalog.view_supplier")
def supplier_list(request):
    suppliers = Supplier.objects.filter(company=request.membership.company, active=True)
    page = Paginator(suppliers, 50).get_page(request.GET.get("page"))
    return render(request, "catalog/supplier_list.html", {"page": page})


@scoped("core.view_workspace", "catalog.add_supplier")
def supplier_create(request):
    form = CounterpartyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_counterparty(
                membership=request.membership,
                actor=request.user,
                name=form.cleaned_data["name"],
                is_supplier=form.cleaned_data["is_supplier"],
                is_customer=form.cleaned_data["is_customer"],
                is_other=form.cleaned_data["is_other"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("supplier_list")
    return render(request, "catalog/supplier_form.html", {"form": form})
