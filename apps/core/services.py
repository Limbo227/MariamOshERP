import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Document, NumberSequence, Organization
from apps.core.quantities import line_amount, q_money, q_price, q_qty


def require_active(obj):
    if getattr(obj, "active", True) is False:
        raise ValidationError(f"«{obj}» отключено и не используется в новых документах.")


def get_organization():
    organization = Organization.objects.select_for_update().first()
    if organization is None:
        raise ValidationError("Сначала создайте карточку организации.")
    return organization


def next_number(kind):
    NumberSequence.objects.get_or_create(kind=kind)
    sequence = NumberSequence.objects.select_for_update().get(kind=kind)
    sequence.last += 1
    sequence.save(update_fields=["last"])
    prefix = {
        Document.Kind.PURCHASE: "PUR",
        Document.Kind.RECEIPT: "RCP",
        Document.Kind.SALE: "SAL",
        Document.Kind.ISSUE: "ISS",
        Document.Kind.MONEY: "MON",
        Document.Kind.PRODUCTION: "PRD",
        Document.Kind.OPENING: "OPN",
        Document.Kind.SETTLEMENT: "SET",
        Document.Kind.REVERSAL: "REV",
    }[kind]
    return f"{prefix}-{sequence.last:06d}"


def draft_document(kind, effective_date, note="", actor=None, reverses=None):
    from apps.core.audit import write_audit
    from apps.core.models import AuditEntry

    get_organization()
    document = Document.objects.create(
        kind=kind,
        number=next_number(kind),
        state=Document.State.DRAFT,
        effective_date=effective_date,
        note=note,
        actor=actor,
        reverses=reverses,
    )
    write_audit(action=AuditEntry.Action.CREATED, document=document, actor=actor)
    return document


def post_document(document, *, snapshot=None):
    from apps.core.audit import write_audit
    from apps.core.models import AuditEntry

    stored = Document.objects.select_for_update().get(pk=document.pk)
    if stored.state == Document.State.POSTED:
        return stored
    stored.state = Document.State.POSTED
    stored.posted_at = timezone.now()
    stored.save(update_fields=["state", "posted_at"])
    document.state = stored.state
    document.posted_at = stored.posted_at
    write_audit(action=AuditEntry.Action.POSTED, document=stored, actor=stored.actor, snapshot=snapshot)
    return stored


def commercial_lines(lines):
    if not lines:
        raise ValidationError("В документе нужна хотя бы одна строка.")
    prepared = []
    for row in lines:
        product = row["product"]
        require_active(product)
        quantity = q_qty(row["quantity"])
        price = q_price(row["price"])
        if quantity <= 0 or price <= 0:
            raise ValidationError("Количество и цена должны быть больше нуля.")
        prepared.append((product, quantity, price, row.get("bags"), line_amount(quantity, price)))
    return prepared


@transaction.atomic
def record_opening(*, effective_date, stock=(), money=(), parties=(), note="Начальные остатки", actor=None):
    from apps.core.models import OpeningBalance, Party
    from apps.finance.models import OpeningMoneyLine, OpeningPartyLine
    from apps.finance.services import add_money, add_open_item, lock_accounts
    from apps.inventory.models import OpeningStockLine
    from apps.inventory.services import add_stock, lock_positions

    if not stock and not money and not parties:
        raise ValidationError("В начальных остатках нужна хотя бы одна строка.")
    prepared_stock = []
    for row in stock:
        product = row["product"]
        location = row["location"]
        require_active(product)
        require_active(location)
        quantity = q_qty(row["quantity"])
        if quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        prepared_stock.append((product, location, quantity, row.get("bags")))
    prepared_money = []
    for row in money:
        account = row["account"]
        require_active(account)
        amount = q_money(row["amount"])
        if amount == 0:
            raise ValidationError("Начальная сумма денег не может быть нулём.")
        prepared_money.append((account, amount))
    prepared_parties = []
    for row in parties:
        party = row["party"]
        require_active(party)
        amount = q_money(row["amount"])
        if amount <= 0:
            raise ValidationError("Начальная сумма долга должна быть больше нуля.")
        prepared_parties.append((party, row["side"], row["lane"], amount, row.get("currency", "KGS")))
    document = draft_document(Document.Kind.OPENING, effective_date, note, actor)
    opening = OpeningBalance.objects.create(document=document)
    for product, location, quantity, bags in prepared_stock:
        OpeningStockLine.objects.create(opening=opening, product=product, location=location, quantity=quantity, bags=bags)
    for account, amount in prepared_money:
        OpeningMoneyLine.objects.create(opening=opening, account=account, amount=amount)
    for party, side, lane, amount, currency in prepared_parties:
        OpeningPartyLine.objects.create(
            opening=opening, party=party, side=side, lane=lane, amount=amount, currency=currency
        )
    if prepared_stock:
        lock_positions((location.id, product.id) for product, location, _quantity, _bags in prepared_stock)
        for product, location, quantity, bags in prepared_stock:
            add_stock(document, product, location, quantity, bags)
    if prepared_money:
        locked = lock_accounts(account for account, _amount in prepared_money)
        for account, amount in prepared_money:
            add_money(document, locked[account.pk], amount)
    for party, side, lane, amount, currency in prepared_parties:
        Party.objects.select_for_update().get(pk=party.pk)
        add_open_item(document, party, side, lane, amount, "Начальный остаток", currency=currency)
    post_document(document)
    return opening


def _guard_dependents(document):
    from apps.inventory.models import IssueLine, ReceiptLine

    if document.kind == Document.Kind.PURCHASE and ReceiptLine.objects.filter(purchase_line__order__document=document).exists():
        raise ValidationError("Сначала разберите приёмки по этой закупке.")
    if document.kind == Document.Kind.SALE and IssueLine.objects.filter(sale_line__sale__document=document).exists():
        raise ValidationError("Сначала разберите выдачи по этой продаже.")


def _guard_foreign_allocations(document):
    from django.db.models import Q

    from apps.finance.models import Allocation

    foreign = Allocation.objects.filter(
        Q(we_owe__document=document) | Q(they_owe__document=document),
        reversal_of__isnull=True,
        reversal__isnull=True,
    ).exclude(document=document)
    if foreign.exists():
        raise ValidationError("Сначала сторнируйте документы, которые зачли эту сумму.")


@transaction.atomic
def reverse_document(document, *, effective_date, note="", actor=None):
    from apps.finance.models import Allocation, MoneyAccount, OpenItem
    from apps.finance.queries import item_remaining
    from apps.finance.services import add_money, add_open_item, allocate_pair, lock_accounts
    from apps.inventory.services import add_stock, lock_positions

    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.state != Document.State.POSTED:
        raise ValidationError("Сторнировать можно только проведённый документ.")
    if document.kind == Document.Kind.REVERSAL:
        raise ValidationError("Сторно само не сторнируется этим действием.")
    if Document.objects.filter(reverses=document).exists():
        raise ValidationError("Документ уже сторнирован.")
    from apps.core.posting import refuse_shipment_receipt

    refuse_shipment_receipt(document)
    _guard_dependents(document)
    _guard_foreign_allocations(document)
    reversal = draft_document(Document.Kind.REVERSAL, effective_date, note, actor, reverses=document)
    stock_moves = list(document.stock_moves.select_related("product", "location"))
    if stock_moves:
        lock_positions((move.location_id, move.product_id) for move in stock_moves)
        for move in stock_moves:
            bags = None if move.bags_delta is None else -move.bags_delta
            add_stock(reversal, move.product, move.location, -move.qty_delta, bags)
    money_moves = list(document.money_moves.select_related("account", "operation"))
    if money_moves:
        lock_accounts(move.account for move in money_moves)
        pair_map = {}
        for move in money_moves:
            pair = pair_map.setdefault(move.pair, uuid.uuid4()) if move.pair else None
            account = MoneyAccount.objects.get(pk=move.account_id)
            add_money(reversal, account, -move.amount_delta, move.operation, pair)
    own_allocations = list(
        Allocation.objects.filter(document=document, reversal_of__isnull=True, reversal__isnull=True).select_related(
            "we_owe", "they_owe"
        )
    )
    for row in own_allocations:
        Allocation.objects.create(
            document=reversal,
            we_owe=row.we_owe,
            they_owe=row.they_owe,
            amount=row.amount,
            reversal_of=row,
            effective_date=effective_date,
        )
    for item in list(document.open_items.all()):
        left = item_remaining(item)
        if left == 0:
            continue
        if left != item.amount:
            raise ValidationError("Позиция закрыта частично. Сначала сторнируйте связанные документы.")
        if item.side == OpenItem.Side.WE_OWE:
            opposite = add_open_item(
                reversal,
                item.party,
                OpenItem.Side.THEY_OWE,
                item.lane,
                left,
                f"Сторно {document.number}",
                order=item.order,
                currency=item.currency,
            )
            allocate_pair(item, opposite, left, reversal)
        else:
            opposite = add_open_item(
                reversal,
                item.party,
                OpenItem.Side.WE_OWE,
                item.lane,
                left,
                f"Сторно {document.number}",
                order=item.order,
                currency=item.currency,
            )
            allocate_pair(opposite, item, left, reversal)
    post_document(reversal)
    return reversal
