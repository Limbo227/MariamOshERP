import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Organization, Party
from apps.finance.models import MoneyAccount, MoneyDocument
from apps.finance.queries import money_balance
from apps.inventory.models import Product, ProductCategory, StorageLocation, Warehouse
from apps.ui.fields import StyledModelForm
from apps.ui.http import erp_page, error_text, pager, toggle_active


class CompanyForm(StyledModelForm):
    class Meta:
        model = Organization
        fields = ["legal_name"]


UNIT_NAMES = {
    Product.Unit.KG: "килограммы (кг)",
    Product.Unit.L: "литры (л)",
    Product.Unit.PCS: "штуки (шт)",
    Product.Unit.BAG: "мешки",
}


class ProductForm(StyledModelForm):
    """One product = one way of counting it.

    Flour «Барс 1 сорт 50 кг» is counted in sacks and knows that one sack is 50 kg:
    500 sacks on stock are shown as «500 меш. (25 000 кг)». Empty sacks are a separate
    packaging product counted in pieces.
    """

    class Meta:
        model = Product
        fields = ["kind", "name", "sku", "category", "unit", "unit_weight_kg", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = ProductCategory.objects.all()
        if not self.instance.pk:
            categories = categories.filter(active=True)
        self.fields["category"].queryset = categories.order_by("name")
        self.fields["category"].required = True
        self.fields["kind"].required = False
        self.fields["category"].help_text = "Группа для складов и отчётов. Склад с категорией принимает только её товары."
        self.fields["kind"].help_text = (
            "Зерно покупается по договору и спецификации вагонами. "
            "Сырьё, материалы и тара — обычным заказом с приёмкой."
        )
        self.fields["name"].help_text = "Пишите так, как говорите: «Мука Барс 1 сорт 50 кг», «Мешок полипропилен под 50 кг»."
        self.fields["sku"].help_text = "Короткий код для поиска, например FLOUR-BARS-1-50."
        self.fields["unit"].choices = [(code, UNIT_NAMES[code]) for code in Product.Unit.values]
        self.fields["unit"].label = "Как считаем"
        self.fields["unit_weight_kg"].label = "Сколько килограммов в одном мешке"
        self.fields["unit_weight_kg"].required = False
        self.fields["unit_weight_kg"].help_text = "Только для товара в мешках. Например 50."
        self.fields["unit_weight_kg"].widget.attrs["placeholder"] = "50"
        self.fields["kind"].widget.attrs["data-kind-units"] = json.dumps(
            {kind: list(units) for kind, units in Product.KIND_UNITS.items()}
        )
        locked = self.instance.pk and self.instance.stock_moves.exists()
        if locked:
            for name in ("category", "unit", "unit_weight_kg"):
                self.fields[name].disabled = True
            self.fields["unit"].help_text = "Товар уже двигался по складу: категория, единица и вес мешка не меняются. Новая фасовка — новый товар."

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("kind"):
            cleaned["kind"] = self.instance.kind or Product.Kind.RAW
        kind = cleaned["kind"]
        unit = cleaned.get("unit") or self.instance.unit
        allowed = Product.KIND_UNITS.get(kind, ())
        if kind and unit and unit not in allowed and not self.fields["unit"].disabled:
            names = ", ".join(UNIT_NAMES[code] for code in allowed)
            self.add_error("unit", f"Для типа «{Product.Kind(kind).label}» подходит: {names}.")
        if unit == Product.Unit.BAG:
            if not cleaned.get("unit_weight_kg"):
                self.add_error("unit_weight_kg", "Укажите, сколько килограммов в одном мешке.")
        elif unit != Product.Unit.KG and not self.fields["unit_weight_kg"].disabled:
            cleaned["unit_weight_kg"] = None
        return cleaned

    def save(self, commit=True):
        product = super().save(commit=False)
        if not self.fields["unit"].disabled:
            # The old «KG + mass of a sack + sack product» way is replaced by «counted in sacks».
            product.package_kg = None
            product.sack = None
        if commit:
            product.save()
        return product


class PartyForm(StyledModelForm):
    class Meta:
        model = Party
        fields = ["name", "is_supplier", "is_customer", "is_employee", "active", "note"]


class WarehouseForm(StyledModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "kind", "category", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].help_text = "Короткий латинский код, например raw или flour."
        self.fields["category"].required = False
        self.fields["category"].queryset = ProductCategory.objects.filter(active=True).order_by("name")
        self.fields["category"].empty_label = "Все категории"
        self.fields["category"].help_text = "Пусто — склад принимает товар любой категории."
        if self.instance.pk and self.instance.category_id and not self.instance.category.active:
            self.fields["category"].queryset = ProductCategory.objects.filter(
                Q(active=True) | Q(pk=self.instance.category_id)
            ).order_by("name")
        if self.instance.pk and self.instance.locations.filter(stock_moves__isnull=False).exists():
            self.fields["kind"].disabled = True
            self.fields["category"].disabled = True


class LocationForm(StyledModelForm):
    class Meta:
        model = StorageLocation
        fields = ["warehouse", "name", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(active=True)
        self.fields["warehouse"].label = "Склад"


class AccountForm(StyledModelForm):
    class Meta:
        model = MoneyAccount
        fields = ["name", "kind", "currency", "overdraft_limit", "active"]

    def __init__(self, *args, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["overdraft_limit"].label = "Допустимый минус"
        if kind and not self.instance.pk:
            self.fields["kind"].initial = kind
            self.fields["kind"].disabled = True
        used = False
        if self.instance.pk:
            used = (
                self.instance.moves.exists()
                or self.instance.opening_lines.exists()
                or self.instance.money_documents.exists()
            )
        if used:
            self.fields["currency"].disabled = True
            self.fields["kind"].disabled = True
            self.fields["currency"].help_text = "Валюту нельзя сменить после движений."


def _save_form(request, form, success, target):
    if form.is_valid():
        try:
            obj = form.save()
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, success)
            return redirect(target, obj.pk)
    return None


@erp_page
def company(request):
    organization = Organization.objects.first()
    form = CompanyForm(request.POST or None, instance=organization)
    if request.method == "POST":
        if organization is None and form.is_valid():
            try:
                form.save()
            except ValidationError as exc:
                form.add_error(None, error_text(exc))
            else:
                messages.success(request, "Карточка организации сохранена.")
                return redirect("company")
        elif organization is not None and form.is_valid():
            try:
                form.save()
            except ValidationError as exc:
                form.add_error(None, error_text(exc))
            else:
                messages.success(request, "Название организации сохранено.")
                return redirect("company")
    return render(request, "ui/company.html", {"form": form, "organization": organization})


@erp_page
def product_list(request):
    qs = Product.objects.select_related("category")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    active = request.GET.get("active", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    kind = request.GET.get("kind", "")
    if category.isdigit():
        qs = qs.filter(category_id=int(category))
    if kind in Product.Kind.values:
        qs = qs.filter(kind=kind)
    if active == "1":
        qs = qs.filter(active=True)
    elif active == "0":
        qs = qs.filter(active=False)
    page, query = pager(request, qs)
    return render(
        request,
        "ui/product_list.html",
        {
            "page": page,
            "query": query,
            "q": q,
            "category": category,
            "active": active,
            "categories": ProductCategory.objects.order_by("name"),
            "kind": kind,
            "kinds": Product.Kind.choices,
        },
    )


@erp_page
def product_create(request):
    form = ProductForm(request.POST or None)
    saved = _save_form(request, form, "Товар сохранён.", "product_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/product_form.html", {"form": form, "product": None, "categories_exist": ProductCategory.objects.filter(active=True).exists()})


@erp_page
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    saved = _save_form(request, form, "Товар сохранён.", "product_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/product_form.html", {"form": form, "product": product, "categories_exist": True})


@erp_page
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    from django.db.models import Sum

    from apps.inventory.models import StockMove
    from apps.ui.formatting import qty_with_weight

    rows = (
        StockMove.objects.filter(product=product)
        .values("location__warehouse__name")
        .annotate(total=Sum("qty_delta"))
        .exclude(total=0)
        .order_by("location__warehouse__name")
    )
    stock = [f"{row['location__warehouse__name']}: {qty_with_weight(product, row['total'])}" for row in rows]
    return render(request, "ui/product_detail.html", {"product": product, "stock": stock})


@erp_page
@require_POST
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    toggle_active(request, product, on_text="Товар включён.", off_text="Товар отключён.")
    return redirect("product_detail", product.pk)


@erp_page
def party_list(request):
    qs = Party.objects.all()
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    active = request.GET.get("active", "")
    if q:
        qs = qs.filter(name__icontains=q)
    if role == "supplier":
        qs = qs.filter(is_supplier=True)
    elif role == "customer":
        qs = qs.filter(is_customer=True)
    elif role == "employee":
        qs = qs.filter(is_employee=True)
    if active == "1":
        qs = qs.filter(active=True)
    elif active == "0":
        qs = qs.filter(active=False)
    page, query = pager(request, qs)
    return render(request, "ui/party_list.html", {"page": page, "query": query, "q": q, "role": role, "active": active})


@erp_page
def party_create(request):
    form = PartyForm(request.POST or None)
    saved = _save_form(request, form, "Контрагент сохранён.", "party_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/party_form.html", {"form": form, "party": None})


@erp_page
def party_edit(request, pk):
    party = get_object_or_404(Party, pk=pk)
    form = PartyForm(request.POST or None, instance=party)
    saved = _save_form(request, form, "Контрагент сохранён.", "party_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/party_form.html", {"form": form, "party": party})


@erp_page
def party_detail(request, pk):
    party = get_object_or_404(Party, pk=pk)
    return render(request, "ui/party_detail.html", {"party": party})


@erp_page
@require_POST
def party_toggle(request, pk):
    party = get_object_or_404(Party, pk=pk)
    toggle_active(request, party, on_text="Контрагент включён.", off_text="Контрагент отключён.")
    return redirect("party_detail", party.pk)


@erp_page
def warehouse_list(request):
    page, query = pager(request, Warehouse.objects.select_related("category"))
    return render(request, "ui/warehouse_list.html", {"page": page, "query": query})


@erp_page
def warehouse_create(request):
    form = WarehouseForm(request.POST or None)
    saved = _save_form(request, form, "Склад сохранён.", "warehouse_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/warehouse_form.html", {"form": form, "warehouse": None})


@erp_page
def warehouse_edit(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    form = WarehouseForm(request.POST or None, instance=warehouse)
    saved = _save_form(request, form, "Склад сохранён.", "warehouse_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/warehouse_form.html", {"form": form, "warehouse": warehouse})


@erp_page
def warehouse_detail(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    locations = warehouse.locations.all()
    return render(request, "ui/warehouse_detail.html", {"warehouse": warehouse, "locations": locations})


@erp_page
@require_POST
def warehouse_toggle(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    toggle_active(request, warehouse, on_text="Склад включён.", off_text="Склад отключён.")
    return redirect("warehouse_detail", warehouse.pk)


@erp_page
def location_list(request):
    qs = StorageLocation.objects.select_related("warehouse")
    warehouse_id = request.GET.get("warehouse", "")
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    page, query = pager(request, qs)
    return render(
        request,
        "ui/location_list.html",
        {"page": page, "query": query, "warehouses": Warehouse.objects.all(), "warehouse_id": warehouse_id},
    )


@erp_page
def location_create(request):
    initial = {}
    warehouse_id = request.GET.get("warehouse")
    if warehouse_id:
        initial["warehouse"] = warehouse_id
    form = LocationForm(request.POST or None, initial=None if request.method == "POST" else initial)
    saved = _save_form(request, form, "Место хранения сохранено.", "location_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/location_form.html", {"form": form, "location": None})


@erp_page
def location_edit(request, pk):
    location = get_object_or_404(StorageLocation, pk=pk)
    form = LocationForm(request.POST or None, instance=location)
    if location.pk:
        form.fields["warehouse"].queryset = Warehouse.objects.filter(Q(active=True) | Q(pk=location.warehouse_id))
    saved = _save_form(request, form, "Место хранения сохранено.", "location_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/location_form.html", {"form": form, "location": location})


@erp_page
def location_detail(request, pk):
    location = get_object_or_404(StorageLocation.objects.select_related("warehouse"), pk=pk)
    return render(request, "ui/location_detail.html", {"location": location})


@erp_page
@require_POST
def location_toggle(request, pk):
    location = get_object_or_404(StorageLocation, pk=pk)
    location.active = not location.active
    try:
        location.save()
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    else:
        messages.success(request, "Место включено." if location.active else "Место отключено.")
    return redirect("location_detail", location.pk)


def _account_queryset(kind):
    return MoneyAccount.objects.filter(kind=kind).order_by("name")


def _with_balance(accounts):
    rows = list(accounts)
    for account in rows:
        account.current_balance = money_balance(account)
    return rows


@erp_page
def account_list(request, kind):
    if kind not in MoneyAccount.Kind.values:
        return redirect("bank_list")
    accounts = _with_balance(_account_queryset(kind))
    title = "Банковские счета" if kind == MoneyAccount.Kind.BANK else "Кассы"
    return render(request, "ui/account_list.html", {"accounts": accounts, "kind": kind, "title": title})


@erp_page
def account_create(request, kind):
    if kind not in MoneyAccount.Kind.values:
        return redirect("bank_list")
    form = AccountForm(request.POST or None, kind=kind)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.kind = kind
        try:
            account.save()
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, "Счёт сохранён.")
            return redirect("account_detail", account.pk)
    title = "Новый банковский счёт" if kind == MoneyAccount.Kind.BANK else "Новая касса"
    return render(request, "ui/account_form.html", {"form": form, "account": None, "title": title, "kind": kind})


@erp_page
def account_edit(request, pk):
    account = get_object_or_404(MoneyAccount, pk=pk)
    form = AccountForm(request.POST or None, instance=account)
    saved = _save_form(request, form, "Счёт сохранён.", "account_detail") if request.method == "POST" else None
    if saved:
        return saved
    title = "Банковский счёт" if account.kind == MoneyAccount.Kind.BANK else "Касса"
    return render(request, "ui/account_form.html", {"form": form, "account": account, "title": title, "kind": account.kind})


@erp_page
def account_detail(request, pk):
    account = get_object_or_404(MoneyAccount, pk=pk)
    account.current_balance = money_balance(account)
    from apps.core.models import Document
    from apps.finance.models import MoneyMove
    from apps.ui.http import show_cancelled, without_cancelled

    cancelled = show_cancelled(request)
    qs = MoneyMove.objects.filter(account=account).select_related("document", "operation")
    if not cancelled:
        qs = without_cancelled(qs)
    moves = list(qs.order_by("-effective_date", "-pk")[:40])
    cancelled_docs = set(
        Document.objects.filter(pk__in=[move.document_id for move in moves])
        .filter(Q(kind=Document.Kind.REVERSAL) | Q(reversal__isnull=False))
        .values_list("pk", flat=True)
    )
    money_of = dict(
        MoneyDocument.objects.filter(document_id__in=[move.document_id for move in moves]).values_list("document_id", "pk")
    )
    for move in moves:
        move.is_cancelled = move.document_id in cancelled_docs
        move.money_id = money_of.get(move.document_id)
    return render(
        request, "ui/account_detail.html", {"account": account, "moves": moves, "cancelled": cancelled}
    )


@erp_page
@require_POST
def account_toggle(request, pk):
    account = get_object_or_404(MoneyAccount, pk=pk)
    toggle_active(request, account, on_text="Счёт включён.", off_text="Счёт отключён.")
    return redirect("account_detail", account.pk)


@erp_page
@require_POST
def product_remove(request, pk):
    product = get_object_or_404(Product, pk=pk)
    from apps.ui.http import remove_or_disable

    return remove_or_disable(request, product, name=product.name, back="product_list", detail=("product_detail", product.pk))


@erp_page
@require_POST
def party_remove(request, pk):
    party = get_object_or_404(Party, pk=pk)
    from apps.ui.http import remove_or_disable

    return remove_or_disable(request, party, name=party.name, back="party_list", detail=("party_detail", party.pk))


@erp_page
@require_POST
def warehouse_remove(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    from apps.ui.http import remove_or_disable

    return remove_or_disable(request, warehouse, name=warehouse.name, back="warehouse_list", detail=("warehouse_detail", warehouse.pk))


@erp_page
@require_POST
def account_remove(request, pk):
    account = get_object_or_404(MoneyAccount, pk=pk)
    from apps.ui.http import remove_or_disable

    back = "cash_list" if account.kind == MoneyAccount.Kind.CASH else "bank_list"
    return remove_or_disable(request, account, name=account.name, back=back, detail=("account_detail", account.pk))
