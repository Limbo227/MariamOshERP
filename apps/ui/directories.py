from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.finance.models import CashOperation, ExpenseCategory
from apps.finance.services import deactivate_expense_category, save_expense_category
from apps.inventory.models import ProductCategory
from apps.inventory.products import deactivate_category, list_units, save_category
from apps.procurement.models import DeliveryTerm, RailwayStation
from apps.procurement.services import save_delivery_term, save_station
from apps.ui.fields import StyledForm
from apps.ui.http import erp_page, error_text, pager


class CategoryForm(StyledForm):
    name = forms.CharField(label="Название")
    code = forms.CharField(label="Код", required=False)
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)
    active = forms.BooleanField(label="Действует", required=False, initial=True)


class StationForm(StyledForm):
    name = forms.CharField(label="Название")
    station_code = forms.CharField(label="Код станции", required=False)
    country = forms.CharField(label="Страна", required=False)
    active = forms.BooleanField(label="Действует", required=False, initial=True)


class TermForm(StyledForm):
    name = forms.CharField(label="Название")
    code = forms.CharField(label="Код", required=False)
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)
    active = forms.BooleanField(label="Действует", required=False, initial=True)


class ExpenseCategoryForm(StyledForm):
    name = forms.CharField(label="Название")
    code = forms.CharField(label="Код", required=False)
    description = forms.CharField(label="Описание", required=False, widget=forms.Textarea)
    active = forms.BooleanField(label="Действует", required=False, initial=True)


def _checked(value):
    return bool(value)


@erp_page
def directory_home(request):
    return render(
        request,
        "ui/directories.html",
        {
            "counts": {
                "categories": ProductCategory.objects.count(),
                "stations": RailwayStation.objects.count(),
                "terms": DeliveryTerm.objects.count(),
                "expenses": ExpenseCategory.objects.count(),
                "units": list_units().count(),
                "operations": CashOperation.objects.filter(active=True).count(),
            }
        },
    )


@erp_page
def category_list(request):
    page, query = pager(request, ProductCategory.objects.order_by("name"))
    return render(request, "ui/category_list.html", {"page": page, "query": query})


@erp_page
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            save_category(
                name=data["name"],
                code=data.get("code") or "",
                description=data.get("description") or "",
                active=_checked(data.get("active")),
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Категория сохранена.")
            back = request.GET.get("next", "")
            if url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}) and back.startswith("/"):
                return redirect(back)
            return redirect("category_list")
    return render(request, "ui/directory_form.html", {"form": form, "heading": "Новая категория", "cancel": "category_list"})


@erp_page
def category_edit(request, pk):
    category = get_object_or_404(ProductCategory, pk=pk)
    initial = {
        "name": category.name,
        "code": category.code,
        "description": category.description,
        "active": category.active,
    }
    form = CategoryForm(request.POST or None, initial=None if request.method == "POST" else initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            save_category(
                name=data["name"],
                code=data.get("code") or category.code,
                description=data.get("description") or "",
                active=_checked(data.get("active")),
                category=category,
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Категория сохранена.")
            return redirect("category_list")
    return render(
        request,
        "ui/directory_form.html",
        {"form": form, "heading": category.name, "cancel": "category_list"},
    )


@erp_page
@require_POST
def category_toggle(request, pk):
    category = get_object_or_404(ProductCategory, pk=pk)
    try:
        if category.active:
            deactivate_category(category, actor=request.user)
            messages.success(request, "Категория отключена.")
        else:
            save_category(
                name=category.name,
                code=category.code,
                description=category.description,
                active=True,
                category=category,
                actor=request.user,
            )
            messages.success(request, "Категория включена.")
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    return redirect("category_list")


@erp_page
def station_list(request):
    page, query = pager(request, RailwayStation.objects.order_by("name"))
    return render(request, "ui/station_list.html", {"page": page, "query": query})


@erp_page
def station_edit(request, pk=None):
    station = get_object_or_404(RailwayStation, pk=pk) if pk else None
    initial = None
    if station and request.method != "POST":
        initial = {
            "name": station.name,
            "station_code": station.station_code,
            "country": station.country,
            "active": station.active,
        }
    form = StationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            save_station(
                name=data["name"],
                station_code=data.get("station_code") or "",
                country=data.get("country") or "",
                active=_checked(data.get("active")),
                station=station,
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Станция сохранена.")
            return redirect("station_list")
    return render(
        request,
        "ui/directory_form.html",
        {
            "form": form,
            "heading": station.name if station else "Новая станция",
            "cancel": "station_list",
        },
    )


@erp_page
def term_list(request):
    page, query = pager(request, DeliveryTerm.objects.order_by("name"))
    return render(request, "ui/term_list.html", {"page": page, "query": query})


@erp_page
def term_edit(request, pk=None):
    term = get_object_or_404(DeliveryTerm, pk=pk) if pk else None
    initial = None
    if term and request.method != "POST":
        initial = {"name": term.name, "code": term.code, "description": term.description, "active": term.active}
    form = TermForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            save_delivery_term(
                name=data["name"],
                code=data.get("code") or "",
                description=data.get("description") or "",
                active=_checked(data.get("active")),
                term=term,
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Условие поставки сохранено.")
            return redirect("term_list")
    return render(
        request,
        "ui/directory_form.html",
        {"form": form, "heading": term.name if term else "Новое условие поставки", "cancel": "term_list"},
    )


@erp_page
def expense_category_list(request):
    page, query = pager(request, ExpenseCategory.objects.order_by("name"))
    return render(request, "ui/expense_category_list.html", {"page": page, "query": query})


@erp_page
def expense_category_edit(request, pk=None):
    category = get_object_or_404(ExpenseCategory, pk=pk) if pk else None
    initial = None
    if category and request.method != "POST":
        initial = {
            "name": category.name,
            "code": category.code,
            "description": category.description,
            "active": category.active,
        }
    form = ExpenseCategoryForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            save_expense_category(
                name=data["name"],
                code=data.get("code") or "",
                description=data.get("description") or "",
                active=_checked(data.get("active")),
                category=category,
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Статья расхода сохранена.")
            return redirect("expense_category_list")
    return render(
        request,
        "ui/directory_form.html",
        {
            "form": form,
            "heading": category.name if category else "Новая статья расхода",
            "cancel": "expense_category_list",
            "note": "Статья выбирается в расходе поставки. Она не создаёт новый вид денежной операции и не меняет проводку.",
        },
    )


@erp_page
@require_POST
def expense_category_toggle(request, pk):
    category = get_object_or_404(ExpenseCategory, pk=pk)
    try:
        if category.active:
            deactivate_expense_category(category, actor=request.user)
            messages.success(request, "Статья отключена.")
        else:
            save_expense_category(
                name=category.name,
                code=category.code,
                description=category.description,
                active=True,
                category=category,
                actor=request.user,
            )
            messages.success(request, "Статья включена.")
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    return redirect("expense_category_list")


def _drop(request, obj, name, back):
    from apps.ui.http import remove_or_disable

    return remove_or_disable(request, obj, name=name, back=back)


@erp_page
@require_POST
def category_delete(request, pk):
    category = get_object_or_404(ProductCategory, pk=pk)
    return _drop(request, category, category.name, "category_list")


@erp_page
@require_POST
def station_delete(request, pk):
    station = get_object_or_404(RailwayStation, pk=pk)
    return _drop(request, station, station.name, "station_list")


@erp_page
@require_POST
def term_delete(request, pk):
    term = get_object_or_404(DeliveryTerm, pk=pk)
    return _drop(request, term, term.name, "term_list")


@erp_page
@require_POST
def expense_category_delete(request, pk):
    category = get_object_or_404(ExpenseCategory, pk=pk)
    return _drop(request, category, category.name, "expense_category_list")


@erp_page
def unit_list(request):
    return render(request, "ui/unit_list.html", {"units": list_units()})


@erp_page
def operation_list(request):
    operations = CashOperation.objects.order_by("effect", "name")
    return render(request, "ui/operation_list.html", {"operations": operations})
