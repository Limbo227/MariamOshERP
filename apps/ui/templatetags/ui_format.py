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


def _url_name(request):
    match = getattr(request, "resolver_match", None)
    return match.url_name if match else ""


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
