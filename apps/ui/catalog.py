from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Organization, Party
from apps.finance.models import MoneyAccount
from apps.finance.queries import money_balance
from apps.inventory.models import Product, ProductCategory, StorageLocation, Warehouse
from apps.ui.fields import StyledModelForm
from apps.ui.http import erp_page, error_text, pager


class CompanyForm(StyledModelForm):
    class Meta:
        model = Organization
        fields = ["legal_name"]


class ProductForm(StyledModelForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "category", "kind", "unit", "unit_weight_kg", "package_kg", "sack", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = ProductCategory.objects.all()
        if not self.instance.pk:
            categories = categories.filter(active=True)
        self.fields["category"].queryset = categories.order_by("name")
        self.fields["category"].required = False
        sacks = Product.objects.filter(kind=Product.Kind.SACK)
        if not self.instance.pk:
            sacks = sacks.filter(active=True)
        self.fields["sack"].queryset = sacks.order_by("name")
        self.fields["sack"].required = False
        self.fields["package_kg"].required = False
        self.fields["unit_weight_kg"].required = False
        self.fields["package_kg"].label = "Масса мешка для учёта в килограммах, кг"
        self.fields["sack"].label = "Пустой мешок"
        locked = self.instance.pk and self.instance.stock_moves.exists()
        if locked:
            for name in ("category", "kind", "unit", "unit_weight_kg", "package_kg", "sack"):
                self.fields[name].disabled = True
            self.fields["kind"].help_text = "Категория, единица, масса единицы, фасовка и мешок не меняются после движений."

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind") or getattr(self.instance, "kind", "")
        unit = cleaned.get("unit") or getattr(self.instance, "unit", "")
        if cleaned.get("category") is not None:
            kind = cleaned["category"].role
        if kind != Product.Kind.FLOUR:
            cleaned["package_kg"] = None
            cleaned["sack"] = None
        elif unit == Product.Unit.BAG:
            cleaned["package_kg"] = None
            if not cleaned.get("unit_weight_kg"):
                self.add_error("unit_weight_kg", "Для товара в мешках укажите массу одного мешка, кг.")
        elif not cleaned.get("package_kg"):
            self.add_error("package_kg", "Для муки в килограммах укажите массу одного мешка.")
        return cleaned


class PartyForm(StyledModelForm):
    class Meta:
        model = Party
        fields = ["name", "is_supplier", "is_customer", "is_employee", "active", "note"]


class WarehouseForm(StyledModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "kind", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].help_text = "Короткий латинский код, например raw или flour."
        if self.instance.pk and self.instance.locations.filter(stock_moves__isnull=False).exists():
            self.fields["kind"].disabled = True


class LocationForm(StyledModelForm):
    class Meta:
        model = StorageLocation
        fields = ["warehouse", "name", "active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(active=True)


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
    qs = Product.objects.all()
    q = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    active = request.GET.get("active", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if kind:
        qs = qs.filter(kind=kind)
    if active == "1":
        qs = qs.filter(active=True)
    elif active == "0":
        qs = qs.filter(active=False)
    page, query = pager(request, qs)
    return render(
        request,
        "ui/product_list.html",
        {"page": page, "query": query, "q": q, "kind": kind, "active": active, "kinds": Product.Kind.choices},
    )


@erp_page
def product_create(request):
    form = ProductForm(request.POST or None)
    saved = _save_form(request, form, "Товар сохранён.", "product_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/product_form.html", {"form": form, "product": None})


@erp_page
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    saved = _save_form(request, form, "Товар сохранён.", "product_detail") if request.method == "POST" else None
    if saved:
        return saved
    return render(request, "ui/product_form.html", {"form": form, "product": product})


@erp_page
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, "ui/product_detail.html", {"product": product})


@erp_page
@require_POST
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.active = not product.active
    try:
        product.save()
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    else:
        messages.success(request, "Товар включён." if product.active else "Товар отключён.")
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
    party.active = not party.active
    try:
        party.save()
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    else:
        messages.success(request, "Контрагент включён." if party.active else "Контрагент отключён.")
    return redirect("party_detail", party.pk)


@erp_page
def warehouse_list(request):
    page, query = pager(request, Warehouse.objects.all())
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
    warehouse.active = not warehouse.active
    warehouse.save()
    messages.success(request, "Склад включён." if warehouse.active else "Склад отключён.")
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
    from apps.finance.models import MoneyMove

    moves = list(
        MoneyMove.objects.filter(account=account).select_related("document", "operation").order_by("-effective_date", "-pk")[:40]
    )
    return render(request, "ui/account_detail.html", {"account": account, "moves": moves})


@erp_page
@require_POST
def account_toggle(request, pk):
    account = get_object_or_404(MoneyAccount, pk=pk)
    account.active = not account.active
    try:
        account.save()
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    else:
        messages.success(request, "Счёт включён." if account.active else "Счёт отключён.")
    return redirect("account_detail", account.pk)
