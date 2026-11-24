from django import template

from apps.ui.formatting import format_money, format_qty, format_rate, unit_label

register = template.Library()


@register.filter
def money(value):
    return format_money(value)


@register.filter
def qty(value):
    return format_qty(value)


@register.filter
def unit(code):
    return unit_label(code)


@register.filter
def rate(value):
    return format_rate(value)


@register.filter
def friendly(value):
    from apps.ui.http import friendly as friendly_text

    return friendly_text(value)


@register.filter
def friendly_list(errors):
    """Each error once, in plain words."""
    from apps.ui.http import friendly as friendly_text

    seen = []
    for error in errors or []:
        text = friendly_text(error)
        if text and text not in seen:
            seen.append(text)
    return seen


@register.filter
def tons(value):
    """Kilograms shown as tonnes: 2 000 000 -> «2 000 т»."""
    if value is None or value == "":
        return ""
    from decimal import Decimal

    return f"{format_qty(Decimal(value) / Decimal(1000))} т"


def _url_name(request):
    match = getattr(request, "resolver_match", None)
    return match.url_name if match else ""


SECTIONS = {
    "dashboard": {"dashboard"},
    "wheat": {
        "wheat_summary",
        "wheat_export",
        "contract_list",
        "contract_create",
        "contract_detail",
        "contract_edit",
        "specification_list",
        "specification_create",
        "shipment_list",
        "shipment_create",
        "shipment_detail",
        "shipment_edit",
        "shipment_wagons",
        "shipment_status",
        "shipment_delete",
        "specification_status",
    },
    "goods": {"materials_monitor", "purchase_list", "purchase_create", "receipt_list", "receipt_create", "receipt_detail"},
    "finance": {
        "finance_home",
        "payment_create",
        "customer_receipt_create",
        "transfer_create",
        "convert_create",
        "expense_create",
        "shipment_expense_create",
        "money_detail",
        "bank_list",
        "cash_list",
    },
    "stock": {"stock_list", "move_list"},
    "reports": {"report_procurement", "report_shipments", "report_suppliers", "report_money"},
}


def current_section(request):
    """Which sidebar item a page belongs to. A purchase page follows its order: spec → wheat, order → goods."""
    name = _url_name(request)
    for section, names in SECTIONS.items():
        if name in names:
            return section
    if name in ("purchase_detail", "purchase_edit", "purchase_delete"):
        from apps.procurement.models import PurchaseOrder

        pk = request.resolver_match.kwargs.get("pk")
        contract = PurchaseOrder.objects.filter(pk=pk).values_list("contract_id", flat=True).first()
        return "wheat" if contract else "goods"
    return "directories"


@register.simple_tag
def section_of(request):
    if not hasattr(request, "_ui_section"):
        request._ui_section = current_section(request)
    return request._ui_section


@register.simple_tag
def section_class(request, section):
    if section_of(request) == section:
        return "block rounded-md bg-teal-brand/20 px-3 py-1.5 text-sm font-medium text-white no-underline"
    return "block rounded-md px-3 py-1.5 text-sm text-slate-300 no-underline hover:bg-navy-800 hover:text-white"


@register.simple_tag
def nav_class(request, *names):
    if _url_name(request) in names:
        return "block rounded-md bg-teal-brand/20 px-3 py-1.5 text-sm font-medium text-white no-underline"
    return "block rounded-md px-3 py-1.5 text-sm text-slate-300 no-underline hover:bg-navy-800 hover:text-white"


@register.simple_tag
def tab_class(request, *names):
    if _url_name(request) in names:
        return "border-b-2 border-teal-brand px-3 py-2 text-sm font-semibold text-teal-800 no-underline"
    return "border-b-2 border-transparent px-3 py-2 text-sm text-slate-600 no-underline hover:text-slate-900"
