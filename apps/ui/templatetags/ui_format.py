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


@register.simple_tag
def nav_class(request, *names):
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match else ""
    if current in names:
        return "block rounded-md bg-slate-800 px-3 py-1.5 text-sm font-medium text-white no-underline"
    return "block rounded-md px-3 py-1.5 text-sm text-slate-300 no-underline hover:bg-slate-900 hover:text-white"
