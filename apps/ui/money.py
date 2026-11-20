from django import forms
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Party
from apps.core.quantities import q_rate
from apps.core.services import reverse_document
from apps.finance.models import (
    CashOperation,
    ExpenseCategory,
    MoneyAccount,
    MoneyDocument,
    OpenItem,
)
from apps.finance.queries import item_remaining, money_balance, supplier_balances
from apps.finance.services import record_money, record_shipment_expense
from apps.procurement.models import PurchaseOrder, Shipment
from apps.ui.fields import StyledForm, date_field, money_field
from apps.ui.formatting import format_rate
from apps.ui.http import erp_page, error_text


def _account_label(account):
    return f"{account.name} — {account.currency}"


def _transfer_label(account):
    return f"{account.name} — {account.get_kind_display()} {account.currency}"


class PaymentForm(StyledForm):
    supplier = forms.ModelChoiceField(label="Поставщик", queryset=Party.objects.none())
    account = forms.ModelChoiceField(label="Счёт списания", queryset=MoneyAccount.objects.none())
    amount = money_field("Сумма")
    effective_date = date_field("Дата оплаты")
    external_reference = forms.CharField(label="Внешний номер", required=False)
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Party.objects.filter(is_supplier=True, active=True).order_by("name")
        self.fields["account"].queryset = MoneyAccount.objects.filter(active=True).order_by("kind", "name")
        self.fields["account"].label_from_instance = lambda account: f"{account.name} — {account.currency}"


class TransferForm(StyledForm):
    account = forms.ModelChoiceField(label="Откуда", queryset=MoneyAccount.objects.none())
    counter_account = forms.ModelChoiceField(label="Куда", queryset=MoneyAccount.objects.none())
    amount = money_field("Сумма")
    effective_date = date_field("Дата")
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = MoneyAccount.objects.filter(active=True).order_by("kind", "name")
        self.fields["account"].queryset = accounts
        self.fields["counter_account"].queryset = accounts
        self.fields["account"].label_from_instance = _transfer_label
        self.fields["counter_account"].label_from_instance = _transfer_label

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("account")
        dest = cleaned.get("counter_account")
        if source and dest and source.pk == dest.pk:
            self.add_error("counter_account", "Выберите два разных счёта.")
        if source and dest and source.currency != dest.currency:
            self.add_error("counter_account", "Перевод только между счетами одной валюты. Для разных валют нужен обмен.")
        return cleaned


class ConvertForm(StyledForm):
    account = forms.ModelChoiceField(label="Счёт списания", queryset=MoneyAccount.objects.none())
    counter_account = forms.ModelChoiceField(label="Счёт зачисления", queryset=MoneyAccount.objects.none())
    amount = money_field("Сумма списания")
    destination_amount = money_field("Сумма зачисления")
    effective_date = date_field("Дата")
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = MoneyAccount.objects.filter(active=True).order_by("name")
        self.fields["account"].queryset = accounts
        self.fields["counter_account"].queryset = accounts
        self.fields["account"].label_from_instance = _account_label
        self.fields["counter_account"].label_from_instance = _account_label

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("account")
        dest = cleaned.get("counter_account")
        if source and dest and source.pk == dest.pk:
            self.add_error("counter_account", "Выберите два разных счёта.")
        if source and dest and source.currency == dest.currency:
            self.add_error("counter_account", "Обмен нужен только для разных валют.")
        return cleaned


class CustomerReceiptForm(StyledForm):
    party = forms.ModelChoiceField(label="Покупатель", queryset=Party.objects.none())
    account = forms.ModelChoiceField(label="Счёт зачисления", queryset=MoneyAccount.objects.none())
    amount = money_field("Сумма")
    effective_date = date_field("Дата")
    external_reference = forms.CharField(label="Внешний номер", required=False)
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["party"].queryset = Party.objects.filter(is_customer=True, active=True).order_by("name")
        self.fields["account"].queryset = MoneyAccount.objects.filter(active=True).order_by("name")
        self.fields["account"].label_from_instance = _account_label


class ShipmentExpenseForm(StyledForm):
    category = forms.ModelChoiceField(label="Статья расхода", queryset=ExpenseCategory.objects.none())
    account = forms.ModelChoiceField(label="Счёт оплаты", queryset=MoneyAccount.objects.none())
    amount = money_field("Сумма")
    effective_date = date_field("Дата")
    order = forms.ModelChoiceField(label="Спецификация", queryset=PurchaseOrder.objects.none(), required=False)
    shipment = forms.ModelChoiceField(label="Поставка", queryset=Shipment.objects.none(), required=False)
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ExpenseCategory.objects.filter(active=True).order_by("name")
        self.fields["account"].queryset = MoneyAccount.objects.filter(active=True).order_by("name")
        self.fields["account"].label_from_instance = _account_label
        self.fields["order"].queryset = PurchaseOrder.objects.select_related("document", "supplier", "contract").order_by(
            "-document__effective_date"
        )
        self.fields["order"].label_from_instance = lambda order: (
            f"{order.contract.number} / {order.specification_number}"
            if order.contract_id
            else order.document.number
        )
        self.fields["order"].empty_label = "Не выбрана — взять из поставки"
        self.fields["shipment"].queryset = Shipment.objects.select_related("order__document", "order__contract").order_by(
            "-pk"
        )
        self.fields["shipment"].empty_label = "На всю спецификацию"
        self.fields["shipment"].label_from_instance = lambda shipment: (
            shipment.wagon_number or f"Поставка {shipment.pk}"
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("order") and not cleaned.get("shipment"):
            self.add_error("order", "Укажите поставку или спецификацию.")
        return cleaned


class ExpenseForm(StyledForm):
    operation = forms.ModelChoiceField(label="Расход", queryset=CashOperation.objects.none())
    account = forms.ModelChoiceField(label="Счёт оплаты", queryset=MoneyAccount.objects.none())
    amount = money_field("Сумма")
    effective_date = date_field("Дата")
    order = forms.ModelChoiceField(label="Закупка", queryset=PurchaseOrder.objects.none(), required=False)
    shipment = forms.ModelChoiceField(label="Вагон", queryset=Shipment.objects.none(), required=False)
    note = forms.CharField(label="Комментарий", required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["operation"].queryset = CashOperation.objects.filter(
            effect=CashOperation.Effect.PAY_EXPENSE, active=True
        )
        self.fields["account"].queryset = MoneyAccount.objects.filter(active=True).order_by("name")
        self.fields["account"].label_from_instance = lambda account: f"{account.name} — {account.currency}"
        self.fields["order"].queryset = PurchaseOrder.objects.select_related("document", "supplier").order_by(
            "-document__effective_date"
        )
        self.fields["order"].label_from_instance = lambda order: f"{order.document.number} — {order.supplier.name}"
        self.fields["order"].empty_label = "Без закупки"
        self.fields["shipment"].queryset = Shipment.objects.select_related("order__document").order_by("-departure_date")
        self.fields["shipment"].label_from_instance = lambda shipment: shipment.wagon_number or f"Отгрузка {shipment.pk}"
        self.fields["shipment"].empty_label = "Без вагона"


def _balances():
    rows = []
    for account in MoneyAccount.objects.order_by("kind", "name"):
        account.current_balance = money_balance(account)
        rows.append(account)
    return rows


def _open_debts(supplier, currency):
    debts = []
    items = OpenItem.objects.filter(
        party=supplier,
        side=OpenItem.Side.WE_OWE,
        lane=OpenItem.Lane.PAYABLE,
        currency=currency,
        document__reversal__isnull=True,
    ).select_related("order__document", "order__contract")
    for item in items:
        left = item_remaining(item)
        if left <= 0:
            continue
        if item.order_id and item.order.specification_number:
            label = f"{item.order.document.number}, спецификация {item.order.specification_number}"
        elif item.order_id:
            label = item.order.document.number
        else:
            label = item.memo or item.document.number
        debts.append({"item": item, "left": left, "label": label})
    return debts


def _allocations(post, debts):
    chosen = []
    known = {row["item"].pk: row["item"] for row in debts}
    for key, raw in post.items():
        if not key.startswith("alloc-") or not str(raw).strip():
            continue
        item = known.get(int(key.split("-", 1)[1])) if key.split("-", 1)[1].isdigit() else None
        if item is None:
            continue
        amount = money_field("Сумма").clean(raw)
        if amount > 0:
            chosen.append({"item": item, "amount": amount})
    return chosen


@erp_page
def finance_home(request):
    accounts = _balances()
    recent = MoneyDocument.objects.select_related(
        "document", "operation", "account", "party", "counter_account", "expense_category"
    ).order_by("-document__effective_date", "-pk")
    effect = request.GET.get("effect", "")
    account_id = request.GET.get("account", "")
    if effect:
        recent = recent.filter(operation__effect=effect)
    if account_id:
        recent = recent.filter(account_id=account_id)
    return render(
        request,
        "ui/finance_home.html",
        {
            "accounts": accounts,
            "balances": supplier_balances(),
            "recent": recent[:40],
            "effect": effect,
            "account": account_id,
            "effects": CashOperation.Effect.choices,
        },
    )


@erp_page
def customer_receipt_create(request):
    form = CustomerReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            operation = CashOperation.objects.get(code="receive-customer", active=True)
            money = record_money(
                operation=operation,
                account=data["account"],
                amount=data["amount"],
                effective_date=data["effective_date"],
                party=data["party"],
                external_reference=data.get("external_reference") or "",
                note=data.get("note") or "",
                actor=request.user,
            )
        except CashOperation.DoesNotExist:
            form.add_error(None, "Операция «Поступление от покупателя» не настроена.")
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(
                request,
                f"Поступление {money.document.number} проведено. Это деньги, без накладной и без склада.",
            )
            return redirect("money_detail", money.pk)
    return render(request, "ui/customer_receipt_form.html", {"form": form})


@erp_page
def shipment_expense_create(request):
    form = ShipmentExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            money = record_shipment_expense(
                account=data["account"],
                amount=data["amount"],
                effective_date=data["effective_date"],
                category=data["category"],
                shipment=data.get("shipment"),
                order=data.get("order"),
                note=data.get("note") or "",
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, f"Расход поставки {money.document.number} проведён. Долг за пшеницу не изменился.")
            return redirect("money_detail", money.pk)
    return render(request, "ui/shipment_expense_form.html", {"form": form})


@erp_page
def payment_create(request):
    supplier_id = request.GET.get("supplier") or request.POST.get("supplier")
    account_id = request.GET.get("account") or request.POST.get("account")
    supplier = Party.objects.filter(pk=supplier_id, is_supplier=True).first() if supplier_id else None
    account = MoneyAccount.objects.filter(pk=account_id).first() if account_id else None
    debts = _open_debts(supplier, account.currency) if supplier and account else []
    form = PaymentForm(request.POST or None)
    if request.method == "GET":
        form = PaymentForm(initial={"supplier": supplier_id, "account": account_id})
    if request.method == "POST" and request.POST.get("action") == "post" and form.is_valid():
        data = form.cleaned_data
        debts = _open_debts(data["supplier"], data["account"].currency)
        try:
            allocations = _allocations(request.POST, debts)
            operation = CashOperation.objects.get(code="pay-supplier", active=True)
            money = record_money(
                operation=operation,
                account=data["account"],
                amount=data["amount"],
                effective_date=data["effective_date"],
                party=data["supplier"],
                external_reference=data.get("external_reference") or "",
                note=data.get("note") or "",
                actor=request.user,
                allocations=allocations or None,
            )
        except CashOperation.DoesNotExist:
            form.add_error(None, "Операция «Оплата поставщику» не настроена.")
        except (ValidationError, forms.ValidationError) as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, f"Оплата {money.document.number} проведена. Склад не изменился.")
            return redirect("money_detail", money.pk)
        supplier = form.cleaned_data.get("supplier") if form.is_valid() else supplier
        account = form.cleaned_data.get("account") if form.is_valid() else account
    return render(
        request,
        "ui/payment_form.html",
        {
            "form": form,
            "supplier": supplier,
            "account": account,
            "debts": debts,
            "suppliers": Party.objects.filter(is_supplier=True, active=True).order_by("name"),
            "accounts": MoneyAccount.objects.filter(active=True).order_by("name"),
        },
    )


@erp_page
def transfer_create(request):
    form = TransferForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        operation = CashOperation.objects.filter(
            effect=CashOperation.Effect.TRANSFER,
            active=True,
            source_kind=data["account"].kind,
            destination_kind=data["counter_account"].kind,
        ).first()
        if operation is None:
            form.add_error(None, "Нет операции перевода для этой пары кассы и банка.")
        else:
            try:
                money = record_money(
                    operation=operation,
                    account=data["account"],
                    counter_account=data["counter_account"],
                    amount=data["amount"],
                    effective_date=data["effective_date"],
                    note=data.get("note") or "",
                    actor=request.user,
                )
            except ValidationError as exc:
                form.add_error(None, error_text(exc))
            else:
                messages.success(request, f"Перевод {money.document.number} проведён.")
                return redirect("money_detail", money.pk)
    return render(request, "ui/transfer_form.html", {"form": form})


def _convert_preview(data):
    try:
        amount = money_field("Сумма").clean(data.get("amount"))
        destination = money_field("Сумма").clean(data.get("destination_amount"))
    except (forms.ValidationError, TypeError):
        return None
    source = MoneyAccount.objects.filter(pk=data.get("account")).first()
    dest = MoneyAccount.objects.filter(pk=data.get("counter_account")).first()
    if not source or not dest or not amount or not destination:
        return None
    rate = q_rate(amount / destination)
    return {
        "source": source,
        "dest": dest,
        "amount": amount,
        "destination": destination,
        "rate": rate,
        "text": f"Курс: {format_rate(rate)} {source.currency}/{dest.currency}",
    }


@erp_page
def convert_create(request):
    form = ConvertForm(request.POST or None)
    preview = _convert_preview(request.POST) if request.method == "POST" else None
    if request.method == "POST" and request.POST.get("action") == "post" and form.is_valid():
        data = form.cleaned_data
        try:
            operation = CashOperation.objects.get(code="convert", active=True)
            money = record_money(
                operation=operation,
                account=data["account"],
                counter_account=data["counter_account"],
                amount=data["amount"],
                destination_amount=data["destination_amount"],
                effective_date=data["effective_date"],
                note=data.get("note") or "",
                actor=request.user,
            )
        except CashOperation.DoesNotExist:
            form.add_error(None, "Операция обмена валюты не настроена.")
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, f"Обмен {money.document.number} проведён. Это не доход, не расход и не оплата поставщику.")
            return redirect("money_detail", money.pk)
    return render(request, "ui/convert_form.html", {"form": form, "preview": preview})


@erp_page
def expense_create(request):
    form = ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            money = record_money(
                operation=data["operation"],
                account=data["account"],
                amount=data["amount"],
                effective_date=data["effective_date"],
                order=data.get("order"),
                shipment=data.get("shipment"),
                note=data.get("note") or "",
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, error_text(exc))
        else:
            messages.success(request, f"Расход {money.document.number} проведён.")
            return redirect("money_detail", money.pk)
    return render(request, "ui/expense_form.html", {"form": form})


@erp_page
def money_detail(request, pk):
    money = get_object_or_404(
        MoneyDocument.objects.select_related(
            "document", "operation", "account", "counter_account", "party", "order__document", "shipment"
        ),
        pk=pk,
    )
    try:
        reversal = money.document.reversal
    except ObjectDoesNotExist:
        reversal = None
    moves = money.document.money_moves.select_related("account")
    return render(
        request,
        "ui/money_detail.html",
        {"money": money, "reversal": reversal, "moves": moves, "today": timezone.localdate()},
    )


@erp_page
@require_POST
def money_reverse(request, pk):
    money = get_object_or_404(MoneyDocument.objects.select_related("document"), pk=pk)
    when = request.POST.get("effective_date") or None
    effective = timezone.localdate()
    if when:
        try:
            effective = date_from(when)
        except ValueError:
            messages.error(request, "Укажите дату сторно.")
            return redirect("money_detail", money.pk)
    try:
        reverse_document(money.document, effective_date=effective, note=request.POST.get("note") or "", actor=request.user)
    except ValidationError as exc:
        messages.error(request, error_text(exc))
    else:
        messages.success(request, "Денежный документ сторнирован.")
    return redirect("money_detail", money.pk)


def date_from(value):
    from datetime import date

    return date.fromisoformat(value)
