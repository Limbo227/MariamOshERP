import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import Currency, Document, Party
from apps.core.quantities import q_money, q_rate
from apps.core.services import draft_document, post_document, require_active
from apps.finance.models import CashOperation, MoneyAccount, MoneyDocument, MoneyMove, OpenItem
from apps.finance.queries import item_remaining


def lock_accounts(accounts):
    ids = sorted({account.pk for account in accounts})
    locked = MoneyAccount.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    return {row.pk: row for row in locked}


def assert_money(account, effective_date, delta):
    rows = list(MoneyMove.objects.filter(account=account).values_list("effective_date", "amount_delta", "pk"))
    rows.append((effective_date, delta, 10**18))
    rows.sort(key=lambda row: (row[0], row[2]))
    running = Decimal("0")
    floor = -account.overdraft_limit
    for _date, amount, _pk in rows:
        running += amount
        if running < floor:
            raise ValidationError(f"Недостаточно денег на счёте «{account}».")


def add_money(document, account, delta, operation=None, pair=None):
    assert_money(account, document.effective_date, delta)
    return MoneyMove.objects.create(
        document=document,
        account=account,
        operation=operation,
        amount_delta=delta,
        pair=pair,
        effective_date=document.effective_date,
    )


def add_open_item(document, party, side, lane, amount, memo, order=None, currency=Currency.KGS):
    currency = str(currency).upper()
    if currency not in Currency.values:
        raise ValidationError("Валюта должна быть KGS, RUB, USD или KZT.")
    if order is not None and order.currency != currency:
        raise ValidationError("Валюта долга должна совпадать с валютой закупки.")
    return OpenItem.objects.create(
        document=document,
        party=party,
        side=side,
        lane=lane,
        amount=q_money(amount),
        effective_date=document.effective_date,
        memo=memo,
        order=order,
        currency=currency,
    )


def allocate_pair(we_owe, they_owe, amount, document):
    from apps.finance.models import Allocation

    amount = q_money(amount)
    if amount <= 0:
        return None
    if we_owe.currency != they_owe.currency:
        raise ValidationError("Зачёт не смешивает валюты.")
    if item_remaining(we_owe) < amount or item_remaining(they_owe) < amount:
        raise ValidationError("Сумма зачёта больше открытого остатка.")
    return Allocation.objects.create(
        document=document,
        we_owe=we_owe,
        they_owe=they_owe,
        amount=amount,
        effective_date=document.effective_date,
    )


def _locked_payable_items(party):
    ids = list(
        OpenItem.objects.filter(party=party, lane=OpenItem.Lane.PAYABLE).order_by("pk").values_list("pk", flat=True)
    )
    if not ids:
        return []
    return list(
        OpenItem.objects.select_for_update(of=("self",))
        .select_related("order")
        .filter(pk__in=ids)
        .order_by("effective_date", "pk")
    )


def _remaining_entries(items, side):
    return [{"item": item, "left": item_remaining(item)} for item in items if item.side == side and item_remaining(item) > 0]


def _pair(document, payment, debt, amount):
    allocate_pair(debt, payment, amount, document)


def apply_supplier_advances(document, party, currency):
    """Close this document's new supplier debt from advances already on the account.

    Oldest advance first. Other приемки are left as they are, so cancelling this
    receipt only gives back the money it took.
    """
    items = _locked_payable_items(party)
    advances = [
        row for row in _remaining_entries(items, OpenItem.Side.THEY_OWE) if row["item"].currency == currency
    ]
    debts = [
        row
        for row in _remaining_entries(items, OpenItem.Side.WE_OWE)
        if row["item"].document_id == document.pk and row["item"].currency == currency
    ]
    _consume(document, advances, debts)


def _close_supplier_payment(document, party, currency, allocations, fifo, *, auto):
    if allocations and fifo:
        raise ValidationError("Укажите либо распределение, либо зачёт по очереди.")
    if allocations:
        _settle_on(document, party, allocations=allocations, fifo=False, currency=currency, allow_empty=True)
        return
    if fifo or auto:
        _settle_on(document, party, allocations=None, fifo=True, currency=currency, allow_empty=True)


def _consume(document, payments, debts):
    allocated = False
    for debt in debts:
        for payment in payments:
            grab = min(debt["left"], payment["left"])
            if grab <= 0:
                continue
            _pair(document, payment["item"], debt["item"], grab)
            debt["left"] -= grab
            payment["left"] -= grab
            allocated = True
            if debt["left"] <= 0:
                break
    return allocated


def _take_amount(document, payments, debts, amount):
    amount = q_money(amount)
    if amount <= 0:
        raise ValidationError("Сумма зачёта должна быть больше нуля.")
    left = amount
    for debt in debts:
        if left <= 0:
            break
        for payment in payments:
            grab = min(debt["left"], payment["left"], left)
            if grab <= 0:
                continue
            _pair(document, payment["item"], debt["item"], grab)
            debt["left"] -= grab
            payment["left"] -= grab
            left -= grab
            if left <= 0 or debt["left"] <= 0:
                break
    if left > 0:
        if sum((row["left"] for row in payments), Decimal("0")) == 0 and left == amount:
            raise ValidationError("Сумма зачёта больше остатка оплаты.")
        raise ValidationError("Сумма зачёта больше открытого долга или остатка оплаты.")


def _settle_on(document, party, *, allocations, fifo, currency=None, allow_empty=False):
    if fifo and allocations:
        raise ValidationError("Укажите либо распределение, либо зачёт по очереди.")
    if not fifo and not allocations:
        raise ValidationError("Укажите, как зачесть оплату.")
    items = _locked_payable_items(party)
    payments = _remaining_entries(items, OpenItem.Side.THEY_OWE)
    debts = _remaining_entries(items, OpenItem.Side.WE_OWE)
    if fifo:
        linked = [row for row in debts if row["item"].order_id]
        currencies = {row["item"].order.currency for row in linked}
        if currency is None and len(currencies) > 1:
            raise ValidationError("Укажите валюту зачёта.")
        chosen = currency or next(iter(currencies), None)
        if chosen is None:
            if not allow_empty:
                raise ValidationError("Нет открытого долга по спецификациям.")
            return
        linked = [row for row in linked if row["item"].order.currency == chosen and row["item"].currency == chosen]
        same_currency = [row for row in payments if row["item"].currency == chosen]
        allocated = _consume(document, same_currency, linked)
        if not allocated and not allow_empty:
            raise ValidationError("Зачёт ничего не закрыл.")
        return
    seen_orders = set()
    seen_items = set()
    currencies = set()
    plan = []
    for row in allocations:
        order = row.get("order")
        item = row.get("item")
        if (order is None) == (item is None):
            raise ValidationError("Укажите спецификацию или одну позицию долга.")
        amount = q_money(row["amount"])
        if amount <= 0:
            raise ValidationError("Сумма зачёта должна быть больше нуля.")
        if order is not None:
            if order.pk in seen_orders:
                raise ValidationError("Спецификация указана в зачёте дважды.")
            seen_orders.add(order.pk)
            if order.supplier_id != party.pk:
                raise ValidationError("Зачёт только по долгу этого поставщика.")
            currencies.add(order.currency)
            targets = [
                entry
                for entry in debts
                if entry["item"].order_id == order.pk and entry["item"].currency == order.currency
            ]
        else:
            if item.pk in seen_items:
                raise ValidationError("Позиция долга указана в зачёте дважды.")
            seen_items.add(item.pk)
            if item.party_id != party.pk or item.side != OpenItem.Side.WE_OWE or item.lane != OpenItem.Lane.PAYABLE:
                raise ValidationError("Зачёт закрывает долг этому поставщику.")
            currencies.add(item.currency)
            targets = [entry for entry in debts if entry["item"].pk == item.pk and entry["item"].currency == item.currency]
        if len(currencies) > 1:
            raise ValidationError("Один зачёт не смешивает валюты.")
        plan.append((targets, amount, order.currency if order is not None else item.currency))
    for targets, amount, deal_currency in plan:
        _take_amount(
            document,
            [row for row in payments if row["item"].currency == deal_currency],
            targets,
            amount,
        )


def auto_allocate(payment_item, document):
    opposite = OpenItem.Side.WE_OWE if payment_item.side == OpenItem.Side.THEY_OWE else OpenItem.Side.THEY_OWE
    targets = OpenItem.objects.filter(
        party=payment_item.party,
        lane=payment_item.lane,
        side=opposite,
        currency=payment_item.currency,
    )
    for target in targets.order_by("effective_date", "pk"):
        take = min(item_remaining(payment_item), item_remaining(target))
        if take <= 0:
            continue
        if payment_item.side == OpenItem.Side.THEY_OWE:
            allocate_pair(target, payment_item, take, document)
        else:
            allocate_pair(payment_item, target, take, document)


def _expense_link(order, shipment):
    if shipment is not None and order is not None and shipment.order_id != order.pk:
        raise ValidationError("Поставка относится к другой спецификации.")
    if shipment is not None and order is None:
        order = shipment.order
    if order is not None and order.document.state != Document.State.POSTED:
        raise ValidationError("Расход привязывают к проведённой закупке.")
    return order, shipment


def _accountable_remaining(party, currency):
    total = Decimal("0")
    items = OpenItem.objects.filter(
        party=party,
        lane=OpenItem.Lane.ACCOUNTABLE,
        side=OpenItem.Side.THEY_OWE,
        currency=currency,
    )
    for item in items:
        total += item_remaining(item)
    return total


def _money_snapshot(operation, account, amount, effect, counter_account=None, destination_amount=None):
    snapshot = {
        "operation": operation.code,
        "effect": effect,
        "account": account.name,
        "currency": account.currency,
        "amount": amount,
    }
    if counter_account is not None and destination_amount is not None:
        snapshot["counter_account"] = counter_account.name
        snapshot["counter_currency"] = counter_account.currency
        snapshot["destination_amount"] = destination_amount
    return snapshot


@transaction.atomic
def record_money(
    *,
    operation,
    account,
    amount,
    effective_date,
    party=None,
    counter_account=None,
    external_reference="",
    note="",
    actor=None,
    allocations=None,
    fifo=None,
    currency=None,
    destination_amount=None,
    rate=None,
    order=None,
    shipment=None,
    expense_category=None,
):
    require_active(operation)
    require_active(account)
    if counter_account is not None:
        require_active(counter_account)
    if party is not None:
        require_active(party)
        Party.objects.select_for_update().get(pk=party.pk)
    amount = q_money(amount)
    if amount <= 0:
        raise ValidationError("Сумма должна быть больше нуля.")
    effect = operation.effect
    if effect == CashOperation.Effect.PAY_PARTY and (party is None or not party.is_supplier):
        raise ValidationError("Оплата контрагенту проводится по поставщику.")
    if effect == CashOperation.Effect.RECEIVE_FROM_PARTY and (party is None or not party.is_customer):
        raise ValidationError("Поступление проводится по покупателю.")
    if effect in (CashOperation.Effect.ACCOUNTABLE, CashOperation.Effect.ACCOUNTABLE_RETURN) and (
        party is None or not party.is_employee
    ):
        raise ValidationError("Подотчёт проводится сотруднику.")
    if effect == CashOperation.Effect.PAY_EXPENSE:
        if party is not None:
            raise ValidationError("Оплата расхода из кассы не создаёт долг. Подотчёт подтверждают отдельно.")
        order, shipment = _expense_link(order, shipment)
    elif effect == CashOperation.Effect.SHIPMENT_EXPENSE:
        if expense_category is None:
            raise ValidationError("Укажите категорию расхода.")
        require_active(expense_category)
        if shipment is None and order is None:
            raise ValidationError("Укажите поставку или спецификацию.")
        order, shipment = _expense_link(order, shipment)
    elif order is not None or shipment is not None:
        raise ValidationError("Закупку и поставку указывают только у расхода.")
    if effect == CashOperation.Effect.ACCOUNTABLE_RETURN:
        held = _accountable_remaining(party, account.currency)
        if amount > held:
            raise ValidationError("Возврат больше выданной подотчётной суммы.")
    if external_reference:
        duplicate = MoneyDocument.objects.filter(
            account=account,
            external_reference=external_reference,
            document__reversal__isnull=True,
        )
        if duplicate.exists():
            raise ValidationError("Этот внешний номер уже проведён по счёту.")
    exchange = effect in (CashOperation.Effect.TRANSFER, CashOperation.Effect.CONVERT)
    if exchange:
        if counter_account is None:
            raise ValidationError("Укажите два разных наших счёта.")
        if account.currency == counter_account.currency:
            if effect == CashOperation.Effect.CONVERT:
                raise ValidationError("Обмен нужен только для разных валют.")
            destination_amount = amount if destination_amount is None else q_money(destination_amount)
            rate = Decimal("1") if rate is None else Decimal(rate)
            if destination_amount != amount or rate != Decimal("1"):
                raise ValidationError("Перевод внутри одной валюты сохраняет ту же сумму.")
        else:
            if effect == CashOperation.Effect.TRANSFER:
                raise ValidationError("Перевод проводится между счетами одной валюты. Для разных валют нужен обмен.")
            if destination_amount is None:
                raise ValidationError("Укажите сумму зачисления.")
            destination_amount = q_money(destination_amount)
            if destination_amount <= 0:
                raise ValidationError("Сумма зачисления должна быть больше нуля.")
            rate = q_rate(amount / destination_amount)
    document = draft_document(Document.Kind.MONEY, effective_date, note, actor)
    MoneyDocument.objects.create(
        document=document,
        operation=operation,
        account=account,
        counter_account=counter_account,
        party=party,
        amount=amount,
        destination_amount=destination_amount if exchange else None,
        rate=rate if exchange else None,
        external_reference=external_reference,
        order=order,
        shipment=shipment,
        expense_category=expense_category,
    )
    locked = lock_accounts([account] if counter_account is None else [account, counter_account])
    account = locked[account.pk]
    if exchange:
        counter_account = locked[counter_account.pk]
        pair = uuid.uuid4()
        add_money(document, account, -amount, operation, pair)
        add_money(document, counter_account, destination_amount, operation, pair)
    elif effect in (
        CashOperation.Effect.PAY_PARTY,
        CashOperation.Effect.PAY_EXPENSE,
        CashOperation.Effect.SHIPMENT_EXPENSE,
        CashOperation.Effect.ACCOUNTABLE,
    ):
        add_money(document, account, -amount, operation)
    elif effect in (CashOperation.Effect.RECEIVE_FROM_PARTY, CashOperation.Effect.ACCOUNTABLE_RETURN):
        add_money(document, account, amount, operation)
    else:
        raise ValidationError("Неизвестный вид операции.")
    if effect == CashOperation.Effect.PAY_PARTY:
        add_open_item(
            document,
            party,
            OpenItem.Side.THEY_OWE,
            OpenItem.Lane.PAYABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
        _close_supplier_payment(document, party, account.currency, allocations, fifo, auto=fifo is None)
    elif effect == CashOperation.Effect.RECEIVE_FROM_PARTY:
        item = add_open_item(
            document,
            party,
            OpenItem.Side.WE_OWE,
            OpenItem.Lane.RECEIVABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
        auto_allocate(item, document)
    elif effect == CashOperation.Effect.ACCOUNTABLE:
        add_open_item(
            document,
            party,
            OpenItem.Side.THEY_OWE,
            OpenItem.Lane.ACCOUNTABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
    elif effect == CashOperation.Effect.ACCOUNTABLE_RETURN:
        item = add_open_item(
            document,
            party,
            OpenItem.Side.WE_OWE,
            OpenItem.Lane.ACCOUNTABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
        auto_allocate(item, document)
    post_document(
        document,
        snapshot=_money_snapshot(
            operation,
            account,
            amount,
            effect,
            counter_account if exchange else None,
            destination_amount if exchange else None,
        ),
    )
    return document.money


@transaction.atomic
def settle_supplier(*, party, effective_date, allocations=None, fifo=False, currency=None, note="", actor=None):
    require_active(party)
    if not party.is_supplier:
        raise ValidationError("Зачёт проводится по поставщику.")
    Party.objects.select_for_update().get(pk=party.pk)
    document = draft_document(Document.Kind.SETTLEMENT, effective_date, note, actor)
    _settle_on(document, party, allocations=allocations, fifo=fifo, currency=currency)
    post_document(document)
    return document


@transaction.atomic
def recognize_accountable(*, advance, operation, amount, effective_date, order=None, shipment=None, note="", actor=None):
    require_active(operation)
    if operation.effect != CashOperation.Effect.PAY_EXPENSE:
        raise ValidationError("Подтверждённый расход проводится операцией расхода.")
    amount = q_money(amount)
    if amount <= 0:
        raise ValidationError("Сумма должна быть больше нуля.")
    advance = (
        OpenItem.objects.select_for_update(of=("self",))
        .select_related("document__money__account", "party")
        .get(pk=advance.pk)
    )
    if advance.side != OpenItem.Side.THEY_OWE or advance.lane != OpenItem.Lane.ACCOUNTABLE:
        raise ValidationError("Подтверждение закрывает выданную подотчётную сумму.")
    if advance.document.state != Document.State.POSTED:
        raise ValidationError("Подотчёт ещё не проведён.")
    if item_remaining(advance) < amount:
        raise ValidationError("Сумма больше остатка подотчёта.")
    order, shipment = _expense_link(order, shipment)
    Party.objects.select_for_update().get(pk=advance.party_id)
    document = draft_document(Document.Kind.MONEY, effective_date, note, actor)
    MoneyDocument.objects.create(
        document=document,
        operation=operation,
        account=advance.document.money.account,
        party=advance.party,
        amount=amount,
        order=order,
        shipment=shipment,
    )
    recognized = add_open_item(
        document,
        advance.party,
        OpenItem.Side.WE_OWE,
        OpenItem.Lane.ACCOUNTABLE,
        amount,
        operation.name,
        currency=advance.currency,
    )
    allocate_pair(recognized, advance, amount, document)
    post_document(
        document,
        snapshot={"effect": operation.effect, "amount": amount, "cash_movement": False},
    )
    return document.money


@transaction.atomic
def record_shipment_expense(
    *,
    account,
    amount,
    effective_date,
    category,
    shipment=None,
    order=None,
    party=None,
    note="",
    actor=None,
    external_reference="",
):
    operation = CashOperation.objects.get(code="shipment-expense")
    require_active(operation)
    return record_money(
        operation=operation,
        account=account,
        amount=amount,
        effective_date=effective_date,
        party=party,
        note=note,
        actor=actor,
        order=order,
        shipment=shipment,
        expense_category=category,
        external_reference=external_reference,
    )


@transaction.atomic
def update_draft_money(money, *, actor=None, **changes):
    from apps.core.audit import write_audit
    from apps.core.models import AuditEntry

    money = (
        MoneyDocument.objects.select_for_update(of=("self",))
        .select_related("document", "account")
        .get(pk=money.pk)
    )
    if money.document.state != Document.State.DRAFT:
        raise ValidationError("Сначала отмените выполнение.")
    previous = {"amount": money.amount, "currency": money.account.currency, "account": money.account.name}
    for key, value in changes.items():
        setattr(money, key, value)
    if "amount" in changes:
        money.amount = q_money(money.amount)
    money.save()
    write_audit(
        action=AuditEntry.Action.UPDATED,
        document=money.document,
        actor=actor,
        detail="Денежный черновик изменён.",
        snapshot={"previous": previous, "new": {"amount": money.amount, "currency": money.account.currency}},
    )
    return money


@transaction.atomic
def repost_money_document(money, *, actor=None, allocations=None, fifo=False, currency=None):
    money = (
        MoneyDocument.objects.select_for_update(of=("self",))
        .select_related("document", "operation", "account", "counter_account", "party", "expense_category")
        .get(pk=money.pk)
    )
    document = Document.objects.select_for_update().get(pk=money.document_id)
    if document.state == Document.State.POSTED:
        return money
    if document.money_moves.exists() or document.open_items.exists() or document.allocations.exists():
        raise ValidationError("У черновика уже есть проводки.")
    effect = money.operation.effect
    if effect == CashOperation.Effect.PAY_EXPENSE and money.party_id:
        raise ValidationError(
            "Подтверждённый подотчётный расход не проводится повторно как выплата из кассы. "
            "Удалите черновик и подтвердите расход заново."
        )
    operation = money.operation
    party = money.party
    amount = money.amount
    account = money.account
    counter_account = money.counter_account
    exchange = effect in (CashOperation.Effect.TRANSFER, CashOperation.Effect.CONVERT)
    locked = lock_accounts([account] if counter_account is None else [account, counter_account])
    account = locked[account.pk]
    if exchange:
        counter_account = locked[counter_account.pk]
        pair = uuid.uuid4()
        add_money(document, account, -amount, operation, pair)
        add_money(document, counter_account, money.destination_amount, operation, pair)
    elif effect in (
        CashOperation.Effect.PAY_PARTY,
        CashOperation.Effect.PAY_EXPENSE,
        CashOperation.Effect.SHIPMENT_EXPENSE,
        CashOperation.Effect.ACCOUNTABLE,
    ):
        add_money(document, account, -amount, operation)
    elif effect in (CashOperation.Effect.RECEIVE_FROM_PARTY, CashOperation.Effect.ACCOUNTABLE_RETURN):
        add_money(document, account, amount, operation)
    else:
        raise ValidationError("Неизвестный вид операции.")
    if effect == CashOperation.Effect.PAY_PARTY:
        add_open_item(
            document,
            party,
            OpenItem.Side.THEY_OWE,
            OpenItem.Lane.PAYABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
        _close_supplier_payment(document, party, account.currency, allocations, fifo, auto=fifo is None)
    elif effect == CashOperation.Effect.RECEIVE_FROM_PARTY:
        item = add_open_item(
            document,
            party,
            OpenItem.Side.WE_OWE,
            OpenItem.Lane.RECEIVABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
        auto_allocate(item, document)
    elif effect == CashOperation.Effect.ACCOUNTABLE:
        add_open_item(
            document,
            party,
            OpenItem.Side.THEY_OWE,
            OpenItem.Lane.ACCOUNTABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
    elif effect == CashOperation.Effect.ACCOUNTABLE_RETURN:
        item = add_open_item(
            document,
            party,
            OpenItem.Side.WE_OWE,
            OpenItem.Lane.ACCOUNTABLE,
            amount,
            operation.name,
            currency=account.currency,
        )
        auto_allocate(item, document)
    if actor is not None and document.actor_id is None:
        document.actor = actor
        document.save(update_fields=["actor"])
    post_document(
        document,
        snapshot=_money_snapshot(
            operation,
            account,
            amount,
            effect,
            counter_account if exchange else None,
            money.destination_amount if exchange else None,
        ),
    )
    return money


@transaction.atomic
def save_expense_category(*, name, code="", description="", active=True, category=None, actor=None):
    from apps.core.audit import write_audit
    from apps.core.models import AuditEntry
    from apps.finance.models import ExpenseCategory
    from apps.procurement.services import _code

    name = (name or "").strip()
    if not name:
        raise ValidationError("Укажите название категории расхода.")
    created = category is None
    if created:
        category = ExpenseCategory(name=name, code=(code or "").strip() or _code(ExpenseCategory, name, "EXP"))
    else:
        category = ExpenseCategory.objects.select_for_update().get(pk=category.pk)
        if code:
            category.code = code.strip()
    category.name = name
    category.description = description or ""
    category.active = active
    category.save()
    write_audit(
        action=AuditEntry.Action.CREATED if created else AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="expense_category",
        target_id=category.pk,
        detail=category.name,
    )
    return category


@transaction.atomic
def deactivate_expense_category(category, *, actor=None):
    from apps.core.audit import write_audit
    from apps.core.models import AuditEntry
    from apps.finance.models import ExpenseCategory

    category = ExpenseCategory.objects.select_for_update().get(pk=category.pk)
    category.active = False
    category.save(update_fields=["active"])
    write_audit(
        action=AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="expense_category",
        target_id=category.pk,
        detail="Категория расхода отключена.",
    )
    return category
