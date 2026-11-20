from datetime import date

from django.shortcuts import render
from django.urls import reverse

from apps.finance.models import MoneyDocument
from apps.inventory.models import GoodsReceipt, Product, ProductCategory, StockMove, Warehouse
from apps.inventory.queries import stock_by_warehouse
from apps.ui.http import erp_page, pager


def _as_of(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@erp_page
def stock_list(request):
    warehouse_id = request.GET.get("warehouse", "")
    product_id = request.GET.get("product", "")
    category_id = request.GET.get("category", "")
    as_of = _as_of(request.GET.get("as_of", ""))
    warehouse = Warehouse.objects.filter(pk=warehouse_id).first() if warehouse_id else None
    product = Product.objects.filter(pk=product_id).first() if product_id else None
    category = ProductCategory.objects.filter(pk=category_id).first() if category_id else None
    balances = stock_by_warehouse(warehouse=warehouse, product=product, category=category, as_of=as_of)
    page, query = pager(request, balances)
    return render(
        request,
        "ui/stock_list.html",
        {
            "rows": page.object_list,
            "page": page,
            "query": query,
            "warehouses": Warehouse.objects.all(),
            "products": Product.objects.all(),
            "categories": ProductCategory.objects.order_by("name"),
            "warehouse": warehouse_id,
            "product": product_id,
            "category": category_id,
            "as_of": request.GET.get("as_of", ""),
        },
    )


@erp_page
def move_list(request):
    qs = StockMove.objects.select_related("document", "product", "location__warehouse").order_by("-effective_date", "-pk")
    warehouse = request.GET.get("warehouse", "")
    product = request.GET.get("product", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if warehouse:
        qs = qs.filter(location__warehouse_id=warehouse)
    if product:
        qs = qs.filter(product_id=product)
    if date_from:
        qs = qs.filter(effective_date__gte=date_from)
    if date_to:
        qs = qs.filter(effective_date__lte=date_to)
    page, query = pager(request, qs)
    moves = list(page.object_list)
    doc_ids = [move.document_id for move in moves]
    receipts = dict(GoodsReceipt.objects.filter(document_id__in=doc_ids).values_list("document_id", "pk"))
    money = dict(MoneyDocument.objects.filter(document_id__in=doc_ids).values_list("document_id", "pk"))
    for move in moves:
        move.ui_url = ""
        if move.document_id in receipts:
            move.ui_url = reverse("receipt_detail", args=[receipts[move.document_id]])
        elif move.document_id in money:
            move.ui_url = reverse("money_detail", args=[money[move.document_id]])
    page.object_list = moves
    return render(
        request,
        "ui/move_list.html",
        {
            "page": page,
            "query": query,
            "warehouses": Warehouse.objects.all(),
            "products": Product.objects.all(),
            "warehouse": warehouse,
            "product": product,
            "date_from": date_from,
            "date_to": date_to,
        },
    )
