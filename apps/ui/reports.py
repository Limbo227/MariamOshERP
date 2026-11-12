from django.db.models import Count, Q
from django.shortcuts import render

from apps.core.models import Party
from apps.finance.models import MoneyAccount
from apps.finance.queries import party_position
from apps.procurement.models import PurchaseOrder, Shipment
from apps.ui.figures import account_flow, order_figures
from apps.ui.http import erp_page, pager


@erp_page
def report_procurement(request):
    qs = PurchaseOrder.objects.select_related("document", "supplier", "contract").order_by(
        "-document__effective_date", "-pk"
    )
    supplier = request.GET.get("supplier", "")
    currency = request.GET.get("currency", "")
    q = request.GET.get("q", "").strip()
    if request.GET.get("reversed") != "1":
        qs = qs.filter(document__reversal__isnull=True)
    if supplier:
        qs = qs.filter(supplier_id=supplier)
    if currency:
        qs = qs.filter(currency=currency)
    if q:
        qs = qs.filter(
            Q(document__number__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(specification_number__icontains=q)
            | Q(contract__number__icontains=q)
        )
    page, query = pager(request, qs, per_page=50)
    rows = list(page.object_list)
    figs = order_figures([row.pk for row in rows])
    for row in rows:
        row.fig = figs[row.pk]
    page.object_list = rows
    return render(
        request,
        "ui/report_procurement.html",
        {
            "page": page,
            "query": query,
            "suppliers": Party.objects.filter(is_supplier=True).order_by("name"),
            "currencies": PurchaseOrder.Currency.choices,
            "supplier": supplier,
            "currency": currency,
            "q": q,
        },
    )


@erp_page
def report_shipments(request):
    counts = {value: 0 for value, _label in Shipment.Status.choices}
    for row in Shipment.objects.values("status").annotate(total=Count("pk")):
        counts[row["status"]] = row["total"]
    qs = Shipment.objects.select_related("order__document", "order__supplier", "order__contract").order_by(
        "-departure_date", "-pk"
    )
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    page, query = pager(request, qs, per_page=50)
    rows = list(page.object_list)
    figs = order_figures([row.order_id for row in rows])
    for row in rows:
        row.fig = figs[row.order_id]
    page.object_list = rows
    return render(
        request,
        "ui/report_shipments.html",
        {"page": page, "query": query, "counts": counts, "statuses": Shipment.Status.choices, "status": status},
    )


@erp_page
def report_suppliers(request):
    rows = []
    for party in Party.objects.filter(is_supplier=True).order_by("name"):
        position = party_position(party)["payable"]
        for currency, bucket in sorted(position.items()):
            payable = bucket.get("we_owe") or 0
            advance = bucket.get("they_owe") or 0
            if not payable and not advance:
                continue
            rows.append({"party": party, "currency": currency, "payable": payable, "advance": advance})
    return render(request, "ui/report_suppliers.html", {"rows": rows})


@erp_page
def report_money(request):
    start = request.GET.get("date_from") or None
    end = request.GET.get("date_to") or None
    rows = []
    for account in MoneyAccount.objects.order_by("kind", "name"):
        flow = account_flow(account, start or None, end or None)
        flow["account"] = account
        rows.append(flow)
    return render(
        request,
        "ui/report_money.html",
        {"rows": rows, "date_from": start or "", "date_to": end or ""},
    )
