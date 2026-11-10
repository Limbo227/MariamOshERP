from django.core.paginator import Paginator
from django.shortcuts import render

from apps.catalog.models import Product, Supplier
from apps.core.access import scoped


@scoped("core.view_workspace", "catalog.view_product")
def product_list(request):
    products = Product.objects.filter(company=request.membership.company).select_related("requirement__component")
    page = Paginator(products, 50).get_page(request.GET.get("page"))
    return render(request, "catalog/product_list.html", {"page": page})


@scoped("core.view_workspace", "catalog.view_supplier")
def supplier_list(request):
    suppliers = Supplier.objects.filter(company=request.membership.company, active=True)
    page = Paginator(suppliers, 50).get_page(request.GET.get("page"))
    return render(request, "catalog/supplier_list.html", {"page": page})
