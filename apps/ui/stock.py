from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render
from django.urls import reverse

from apps.finance.models import MoneyDocument
from apps.inventory.models import GoodsReceipt, Product, StockMove, Warehouse
from apps.ui.http import erp_page, pager


@erp_page
def stock_list(request):
    qs = StockMove.objects.values(
        "location__warehouse__name",
        "location__name",
        "product__name",
        "product__sku",
        "product__unit",
    ).annotate(quantity=Sum("qty_delta"))
    warehouse = request.GET.get("warehouse", "")
    product = request.GET.get("product", "")
    if warehouse:
        qs = qs.filter(location__warehouse_id=warehouse)
    if product:
        qs = qs.filter(product_id=product)
    qs = qs.exclude(quantity=0).order_by("location__warehouse__name", "location__name", "product__name")
    page, query = pager(request, qs)
    rows = [
        {
            "warehouse": row["location__warehouse__name"],
            "location": row["location__name"],
            "product": row["product__name"],
            "sku": row["product__sku"],
            "quantity": row["quantity"] or Decimal("0"),
            "unit": row["product__unit"],
        }
        for row in page.object_list
    ]
    return render(
        request,
        "ui/stock_list.html",
        {
            "rows": rows,
            "page": page,
            "query": query,
            "warehouses": Warehouse.objects.all(),
            "products": Product.objects.all(),
            "warehouse": warehouse,
            "product": product,
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
