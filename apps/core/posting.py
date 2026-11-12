"""Reversible posting: undo the ledger of one document and return it to draft."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.core.audit import write_audit
from apps.core.lifecycle import lifecycle
from apps.core.models import AuditEntry, Document


def _guard_dependents(document):
    from apps.inventory.models import IssueLine, ReceiptLine
    from apps.procurement.models import Shipment

    if document.kind == Document.Kind.PURCHASE:
        if ReceiptLine.objects.filter(
            purchase_line__order__document=document,
            receipt__document__state=Document.State.POSTED,
        ).exists():
            raise ValidationError(
                "Нельзя отменить выполнение спецификации: есть проведённая приёмка. Сначала отмените приёмку."
            )
        if Shipment.objects.filter(order__document=document, status=Shipment.State.POSTED).exists():
            raise ValidationError(
                "Нельзя отменить выполнение спецификации: есть проведённая поставка. Сначала отмените поставку."
            )
    if document.kind == Document.Kind.SALE and IssueLine.objects.filter(
        sale_line__sale__document=document,
        issue__document__state=Document.State.POSTED,
    ).exists():
        raise ValidationError(
            "Нельзя отменить выполнение продажи: есть проведённая выдача. Сначала отмените выдачу."
        )


def _assert_stock_removable(document):
    from apps.inventory.models import StockMove

    moves = list(document.stock_moves.select_related("product", "location"))
    keys = {(move.location_id, move.product_id) for move in moves}
    for location_id, product_id in keys:
        rows = (
            StockMove.objects.filter(location_id=location_id, product_id=product_id)
            .exclude(document=document)
            .select_related("document", "product")
            .order_by("effective_date", "pk")
        )
        quantity = Decimal("0")
        bags = 0
        for row in rows:
            quantity += row.qty_delta
            if quantity < 0:
                raise ValidationError(
                    f"Нельзя отменить выполнение: документ {row.document.number} списывает «{row.product}», "
                    "и остатка не хватит."
                )
            if row.bags_delta is not None:
                bags += row.bags_delta
                if bags < 0:
                    raise ValidationError(
                        f"Нельзя отменить выполнение: документ {row.document.number} списывает мешки «{row.product}», "
                        "и остатка не хватит."
                    )


def _assert_money_removable(document):
    from apps.finance.models import MoneyAccount, MoneyMove

    account_ids = set(document.money_moves.values_list("account_id", flat=True))
    for account_id in account_ids:
        account = MoneyAccount.objects.get(pk=account_id)
        rows = (
            MoneyMove.objects.filter(account_id=account_id)
            .exclude(document=document)
            .select_related("document")
            .order_by("effective_date", "pk")
        )
        running = Decimal("0")
        floor = -account.overdraft_limit
        for row in rows:
            running += row.amount_delta
            if running < floor:
                raise ValidationError(
                    f"Нельзя отменить выполнение: на счёте «{account}» документ {row.document.number} "
                    "оставит недостаток денег."
                )


def refuse_shipment_receipt(document):
    if document.kind != Document.Kind.RECEIPT:
        return
    from apps.procurement.models import Shipment

    if Shipment.objects.filter(receipt__document=document).exists():
        raise ValidationError(
            "Эта приёмка создана проведением поставки. Отмените выполнение поставки, а не приёмку отдельно."
        )


def ledger_snapshot(document):
    from apps.finance.models import Allocation

    stock = [
        {
            "product": move.product.sku,
            "warehouse": move.location.warehouse.code,
            "quantity": move.qty_delta,
            "bags": move.bags_delta,
            "unit": move.unit_code,
            "unit_weight_kg": move.unit_weight_kg,
        }
        for move in document.stock_moves.select_related("product", "location__warehouse")
    ]
    money = [
        {"account": move.account.name, "currency": move.account.currency, "amount": move.amount_delta}
        for move in document.money_moves.select_related("account")
    ]
    items = list(document.open_items.all())
    open_items = [
        {"side": item.side, "lane": item.lane, "currency": item.currency, "amount": item.amount, "memo": item.memo}
        for item in items
    ]
    item_ids = [item.pk for item in items]
    allocations = []
    rows = Allocation.objects.filter(
        Q(document=document) | Q(we_owe_id__in=item_ids) | Q(they_owe_id__in=item_ids)
    ).select_related("document", "we_owe__document", "they_owe__document")
    for row in rows:
        allocations.append(
            {
                "amount": row.amount,
                "payment_document": row.document.number,
                "debt_document": row.we_owe.document.number,
                "credit_document": row.they_owe.document.number,
            }
        )
    return {"stock": stock, "money": money, "open_items": open_items, "allocations": allocations}


def _draft_snapshot(document):
    data = {"number": document.number, "kind": document.kind, "effective_date": document.effective_date}
    if document.kind == Document.Kind.RECEIPT:
        data["lines"] = [
            {"product": line.product.sku, "quantity": line.quantity}
            for line in document.receipt.lines.select_related("product")
        ]
    elif document.kind == Document.Kind.ISSUE:
        data["lines"] = [
            {"product": line.product.sku, "quantity": line.quantity}
            for line in document.issue.lines.select_related("product")
        ]
    elif document.kind == Document.Kind.SALE:
        data["lines"] = [
            {"product": line.product.sku, "quantity": line.quantity, "price": line.price, "amount": line.amount}
            for line in document.sale.lines.select_related("product")
        ]
    elif document.kind == Document.Kind.MONEY:
        money = document.money
        data.update(
            {
                "account": money.account.name,
                "currency": money.account.currency,
                "amount": money.amount,
                "effect": money.operation.effect,
            }
        )
    elif document.kind == Document.Kind.PRODUCTION:
        data["outputs"] = [
            {"product": line.product.sku, "quantity": line.quantity, "bags": line.bags}
            for line in document.production.outputs.select_related("product")
        ]
        data["inputs"] = [
            {"product": line.product.sku, "quantity": line.quantity}
            for line in document.production.inputs.select_related("product")
        ]
    return data


def _clear_effects(document, actor):
    from apps.finance.models import Allocation, MoneyMove, OpenItem
    from apps.inventory.models import StockMove

    item_ids = list(document.open_items.values_list("pk", flat=True))
    allocs = Allocation.objects.filter(Q(document=document) | Q(we_owe_id__in=item_ids) | Q(they_owe_id__in=item_ids))
    foreign = list(
        allocs.exclude(document=document).select_related("document", "we_owe__document", "they_owe__document")
    )
    ids = list(allocs.values_list("pk", flat=True))
    for row in foreign:
        write_audit(
            action=AuditEntry.Action.UNPOSTED,
            document=row.document,
            actor=actor,
            detail=(
                f"Снят зачёт {row.amount} по документу {document.number}. "
                "Платёж сохранён как нераспределённая сумма."
            ),
            target_type="allocation",
            target_id=row.pk,
            snapshot={
                "amount": row.amount,
                "payment_document": row.document.number,
                "debt_document": row.we_owe.document.number,
                "credit_document": row.they_owe.document.number,
            },
        )
    if ids:
        Allocation.objects.filter(reversal_of_id__in=ids).delete()
        Allocation.objects.filter(pk__in=ids).delete()
    OpenItem.objects.filter(document=document).delete()
    MoneyMove.objects.filter(document=document).delete()
    StockMove.objects.filter(document=document).delete()


@transaction.atomic
def unpost_document(document, *, actor=None, detail=""):
    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.state != Document.State.POSTED:
        raise ValidationError("Отменить выполнение можно только у проведённого документа.")
    if document.kind == Document.Kind.REVERSAL:
        raise ValidationError("Сторно не возвращают в черновик.")
    if document.kind == Document.Kind.OPENING:
        raise ValidationError(
            "Начальные остатки не возвращают в черновик: повторное проведение заново записало бы "
            "исторический остаток. Исправление делается сторно, если последующие движения это позволяют."
        )
    if document.kind == Document.Kind.SETTLEMENT:
        raise ValidationError(
            "Зачёт не возвращают в черновик: состав зачёта не хранится отдельным черновиком. "
            "Снимите зачёт сторно, чтобы сохранить, какой платёж закрывал какой долг."
        )
    if Document.objects.filter(reverses=document).exists():
        raise ValidationError("Документ уже сторнирован. Отмена выполнения недоступна.")
    refuse_shipment_receipt(document)
    _guard_dependents(document)
    _assert_stock_removable(document)
    _assert_money_removable(document)
    snapshot = ledger_snapshot(document)
    _clear_effects(document, actor)
    document.state = Document.State.DRAFT
    document.posted_at = None
    with lifecycle():
        document.save(update_fields=["state", "posted_at"])
    write_audit(
        action=AuditEntry.Action.UNPOSTED,
        document=document,
        actor=actor,
        detail=detail,
        snapshot=snapshot,
    )
    return document


def _delete_children(document):
    from apps.finance.models import MoneyDocument, OpeningMoneyLine, OpeningPartyLine, OpenItem
    from apps.inventory.models import (
        GoodsIssue,
        GoodsReceipt,
        IssueLine,
        OpeningStockLine,
        ReceiptLine,
    )
    from apps.procurement.models import PurchaseLine, PurchaseOrder, Shipment
    from apps.production.models import InputLine, OutputLine
    from apps.sales.models import SaleLine

    kind = document.kind
    if kind == Document.Kind.PURCHASE:
        order = PurchaseOrder.objects.get(document=document)
        if Shipment.objects.filter(order=order).exists():
            raise ValidationError("Сначала удалите поставки этой спецификации.")
        if order.expenses.exists():
            raise ValidationError("Сначала отвяжите расходы от этой спецификации.")
        if OpenItem.objects.filter(order=order).exists():
            raise ValidationError("По спецификации есть долг. Сначала отмените связанные приёмки.")
        PurchaseLine.objects.filter(order=order).delete()
        order.delete()
    elif kind == Document.Kind.RECEIPT:
        receipt = GoodsReceipt.objects.get(document=document)
        if Shipment.objects.filter(receipt=receipt).exists():
            raise ValidationError("Приёмка связана с поставкой. Сначала отмените поставку.")
        ReceiptLine.objects.filter(receipt=receipt).delete()
        receipt.delete()
    elif kind == Document.Kind.ISSUE:
        issue = GoodsIssue.objects.get(document=document)
        IssueLine.objects.filter(issue=issue).delete()
        issue.delete()
    elif kind == Document.Kind.SALE:
        sale = document.sale
        if IssueLine.objects.filter(sale_line__sale=sale).exists():
            raise ValidationError("Сначала удалите выдачи по этой продаже.")
        SaleLine.objects.filter(sale=sale).delete()
        sale.delete()
    elif kind == Document.Kind.MONEY:
        MoneyDocument.objects.filter(document=document).delete()
    elif kind == Document.Kind.PRODUCTION:
        report = document.production
        OutputLine.objects.filter(report=report).delete()
        InputLine.objects.filter(report=report).delete()
        report.delete()
    elif kind == Document.Kind.OPENING:
        opening = document.opening
        OpeningStockLine.objects.filter(opening=opening).delete()
        OpeningMoneyLine.objects.filter(opening=opening).delete()
        OpeningPartyLine.objects.filter(opening=opening).delete()
        opening.delete()
    elif kind == Document.Kind.SETTLEMENT:
        return
    elif kind == Document.Kind.REVERSAL:
        raise ValidationError("Сторно не удаляется.")


@transaction.atomic
def delete_draft_document(document, *, actor=None):
    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.state != Document.State.DRAFT:
        raise ValidationError("Проведённый документ нельзя удалить. Сначала отмените выполнение.")
    if document.stock_moves.exists() or document.money_moves.exists() or document.open_items.exists():
        raise ValidationError("У документа остались проводки. Сначала отмените выполнение.")
    if document.allocations.exists():
        raise ValidationError("У документа остались зачёты. Сначала отмените выполнение.")
    if Document.objects.filter(reverses=document).exists() or document.reverses_id:
        raise ValidationError("Документ связан со сторно и не удаляется.")
    refuse_shipment_receipt(document)
    number = document.number
    kind = document.kind
    snapshot = _draft_snapshot(document)
    _delete_children(document)
    write_audit(
        action=AuditEntry.Action.DELETED,
        document=document,
        actor=actor,
        number=number,
        kind=kind,
        detail="Черновик удалён.",
        snapshot=snapshot,
    )
    with lifecycle():
        document.delete()
