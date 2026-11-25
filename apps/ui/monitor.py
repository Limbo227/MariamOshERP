"""Read-only purchase monitors.

Figures come from posted receipts, open items and allocations. Draft shipment
weight is shown beside the actuals and is never added to them. Currencies are
not combined.
"""

import csv
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render

from apps.core.quantities import line_amount
from apps.inventory.models import Product, ProductCategory
from apps.procurement.models import PurchaseContract, PurchaseOrder, RailwayStation, Shipment
from apps.procurement.reports import shipment_purchase_amount, specification_progress
from apps.ui.figures import fill_percent, order_figures
from apps.ui.http import erp_page, pager, remember_list

TONNE = Decimal("1000")


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _specification_orders(request):
    qs = (
        PurchaseOrder.objects.filter(contract__isnull=False)
        .select_related("document", "supplier", "contract", "delivery_term")
        .prefetch_related("lines__product", "shipments__departure_station", "shipments__wagons")
    )
    q = request.GET.get("q", "").strip()
    supplier = request.GET.get("supplier", "")
    contract = request.GET.get("contract", "")
    product = request.GET.get("product", "")
    status = request.GET.get("status", "")
    station = request.GET.get("station", "")
    date_from = _parse_date(request.GET.get("date_from", ""))
    date_to = _parse_date(request.GET.get("date_to", ""))
    if q:
        qs = qs.filter(
            Q(supplier__name__icontains=q)
            | Q(contract__number__icontains=q)
            | Q(specification_number__icontains=q)
            | Q(lines__product__name__icontains=q)
        )
    if supplier:
        qs = qs.filter(supplier_id=supplier)
    if contract:
        qs = qs.filter(contract_id=contract)
    if product:
        qs = qs.filter(lines__product_id=product)
    if status in PurchaseOrder.OperationalStatus.values:
        qs = qs.filter(operational_status=status)
    if station:
        qs = qs.filter(shipments__departure_station_id=station)
    if date_from:
        qs = qs.filter(document__effective_date__gte=date_from)
    if date_to:
        qs = qs.filter(document__effective_date__lte=date_to)
    sort = request.GET.get("sort", "supplier")
    ordering = {
        "supplier": ("supplier__name", "contract__number", "specification_number"),
        "contract": ("contract__number", "specification_number"),
        "date": ("-document__effective_date", "supplier__name"),
        "status": ("operational_status", "supplier__name"),
    }.get(sort, ("supplier__name", "contract__number", "specification_number"))
    return qs.distinct().order_by(*ordering)


def _row(order, figures):
    line = order.lines.all()[0] if order.lines.all() else None
    fig = figures[order.pk]
    progress = specification_progress(order)
    price = line.price if line is not None else None
    unit = line.product.unit if line is not None else ""
    draft_amount = None
    if price is not None and unit == Product.Unit.KG:
        draft_amount = line_amount(fig["draft_qty"], price)
    percent = progress["received_percent"]
    shipments = []
    for shipment in order.shipments.all():
        amount, currency = shipment_purchase_amount(shipment)
        theoretical = None
        if shipment.status != Shipment.Status.POSTED and price is not None and unit == Product.Unit.KG:
            theoretical = line_amount(shipment.quantity, price)
        shipments.append(
            {
                "shipment": shipment,
                "amount": amount,
                "theoretical": theoretical,
                "currency": currency,
                "price": price,
            }
        )
    return {
        "order": order,
        "line": line,
        "product": line.product if line is not None else None,
        "price": price,
        "unit": unit,
        "planned_qty": fig["planned_qty"],
        "planned_tonnes": (fig["planned_qty"] / TONNE) if unit == Product.Unit.KG else None,
        "received_qty": fig["accepted_qty"],
        "received_tonnes": (fig["accepted_qty"] / TONNE) if unit == Product.Unit.KG else None,
        "draft_qty": fig["draft_qty"],
        "difference": fig["accepted_qty"] - fig["planned_qty"],
        "percent": percent,
        "bar": min(percent or Decimal("0"), Decimal("100")),
        "tolerance": order.tolerance_percent,
        "planned_amount": fig["planned_amount"],
        "accepted_amount": fig["accepted_amount"],
        "draft_amount": draft_amount,
        "paid": fig["paid"],
        "outstanding": fig["outstanding"],
        "currency": order.currency,
        "status": order.operational_status,
        "status_label": order.get_operational_status_display(),
        "warning": progress["warning"],
        "shipments": shipments,
    }


def _totals(rows):
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault(
            row["currency"],
            {
                "currency": row["currency"],
                "planned_amount": Decimal("0.00"),
                "accepted_amount": Decimal("0.00"),
                "paid": Decimal("0.00"),
                "outstanding": Decimal("0.00"),
                "planned_qty": Decimal("0"),
                "received_qty": Decimal("0"),
            },
        )
        bucket["planned_amount"] += row["planned_amount"]
        bucket["accepted_amount"] += row["accepted_amount"]
        bucket["paid"] += row["paid"]
        bucket["outstanding"] += row["outstanding"]
        if row["unit"] == Product.Unit.KG:
            bucket["planned_qty"] += row["planned_qty"]
            bucket["received_qty"] += row["received_qty"]
    return [buckets[key] for key in sorted(buckets)]


def _groups(rows):
    suppliers = []
    by_supplier = {}
    for row in rows:
        supplier = row["order"].supplier
        contract = row["order"].contract
        supplier_group = by_supplier.get(supplier.pk)
        if supplier_group is None:
            supplier_group = {"supplier": supplier, "contracts": [], "by_contract": {}}
            by_supplier[supplier.pk] = supplier_group
            suppliers.append(supplier_group)
        contract_group = supplier_group["by_contract"].get(contract.pk)
        if contract_group is None:
            contract_group = {"contract": contract, "rows": []}
            supplier_group["by_contract"][contract.pk] = contract_group
            supplier_group["contracts"].append(contract_group)
        contract_group["rows"].append(row)
    for supplier_group in suppliers:
        for contract_group in supplier_group["contracts"]:
            contract_group["totals"] = _totals(contract_group["rows"])
        supplier_group.pop("by_contract")
    return suppliers


def _context(request, rows, page=None, query=""):
    from apps.core.models import Party

    return {
        "groups": _groups(rows),
        "totals": _totals(rows),
        "page": page,
        "query": query,
        "q": request.GET.get("q", ""),
        "supplier": request.GET.get("supplier", ""),
        "contract": request.GET.get("contract", ""),
        "product": request.GET.get("product", ""),
        "status": request.GET.get("status", ""),
        "station": request.GET.get("station", ""),
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
        "sort": request.GET.get("sort", "supplier"),
        "suppliers": Party.objects.filter(is_supplier=True).order_by("name"),
        "contracts": PurchaseContract.objects.select_related("supplier").order_by("number"),
        "products": Product.objects.filter(kind=Product.Kind.GRAIN, active=True).order_by("name"),
        "stations": RailwayStation.objects.filter(active=True).order_by("name"),
        "statuses": PurchaseOrder.OperationalStatus.choices,
    }


def _page_rows(orders):
    orders = list(orders)
    figures = order_figures([order.pk for order in orders])
    return [_row(order, figures) for order in orders]


@erp_page
def wheat_summary(request):
    remember_list(request, "wheat")
    orders = _specification_orders(request)
    page, query = pager(request, orders, per_page=40)
    rows = _page_rows(page.object_list)
    return render(request, "ui/wheat_summary.html", _context(request, rows, page, query))


@erp_page
def wheat_export(request):
    orders = _specification_orders(request)
    rows = _page_rows(orders)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="svod.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Поставщик",
            "Договор",
            "Спецификация",
            "Товар",
            "Валюта",
            "Цена за кг",
            "План, кг",
            "Принято проведённое, кг",
            "Черновик, кг",
            "Исполнение, %",
            "Допуск, %",
            "План, сумма",
            "Принято, сумма",
            "Черновик, расчёт",
            "Оплачено",
            "Остаток долга",
            "Состояние",
        ]
    )
    def cell(value):
        """Numbers with a decimal comma and no trailing zeros, so Russian Excel reads them as numbers."""
        if value is None or value == "":
            return ""
        if isinstance(value, (Decimal, int, float)):
            text = f"{Decimal(value):f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return text.replace(".", ",")
        return value

    for row in rows:
        writer.writerow(
            [
                cell(value)
                for value in (
                    row["order"].supplier.name,
                row["order"].contract.number,
                row["order"].specification_number,
                row["product"].name if row["product"] else "",
                row["currency"],
                row["price"] if row["price"] is not None else "",
                row["planned_qty"],
                row["received_qty"],
                row["draft_qty"],
                row["percent"] if row["percent"] is not None else "",
                row["tolerance"],
                row["planned_amount"],
                row["accepted_amount"],
                row["draft_amount"] if row["draft_amount"] is not None else "",
                row["paid"],
                row["outstanding"],
                row["status_label"],
                )
            ]
        )
    return response


@erp_page
def materials_monitor(request):
    remember_list(request, "materials")
    from apps.core.models import Party

    qs = (
        PurchaseOrder.objects.filter(contract__isnull=True)
        .select_related("document", "supplier")
        .prefetch_related("lines__product")
        .order_by("-document__effective_date", "-pk")
    )
    q = request.GET.get("q", "").strip()
    supplier = request.GET.get("supplier", "")
    category = request.GET.get("category", "")
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(document__number__icontains=q) | Q(supplier__name__icontains=q) | Q(lines__product__name__icontains=q))
    if supplier:
        qs = qs.filter(supplier_id=supplier)
    if category.isdigit():
        qs = qs.filter(lines__product__category_id=int(category))
    if status in PurchaseOrder.OperationalStatus.values:
        qs = qs.filter(operational_status=status)
    page, query = pager(request, qs.distinct())
    orders = list(page.object_list)
    figures = order_figures([order.pk for order in orders])
    for order in orders:
        order.fig = figures[order.pk]
        order.ui_lines = list(order.lines.all())
        order.ui_percent = fill_percent(order.fig["planned_qty"], order.fig["accepted_qty"])
    page.object_list = orders
    return render(
        request,
        "ui/materials_monitor.html",
        {
            "page": page,
            "query": query,
            "q": q,
            "supplier": supplier,
            "category": category,
            "status": status,
            "statuses": PurchaseOrder.OperationalStatus.choices,
            "suppliers": Party.objects.filter(is_supplier=True).order_by("name"),
            "categories": ProductCategory.objects.order_by("name"),
        },
    )
