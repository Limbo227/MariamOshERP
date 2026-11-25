from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.core.models import Document
from apps.core.quantities import line_amount, q_qty
from apps.core.services import draft_document, post_document, require_active
from apps.inventory.models import (
    GoodsIssue,
    GoodsReceipt,
    IssueLine,
    ReceiptLine,
    StockMove,
    StockPosition,
)


def lock_positions(pairs):
    ids = []
    for location_id, product_id in sorted(set(pairs)):
        position, _created = StockPosition.objects.get_or_create(location_id=location_id, product_id=product_id)
        ids.append(position.pk)
    if ids:
        list(StockPosition.objects.select_for_update().filter(pk__in=ids).order_by("pk"))


def assert_stock(location_id, product_id, effective_date, qty_delta, bags_delta):
    rows = list(
        StockMove.objects.filter(location_id=location_id, product_id=product_id).values_list(
            "effective_date", "qty_delta", "bags_delta", "pk"
        )
    )
    rows.append((effective_date, qty_delta, bags_delta, 10**18))
    rows.sort(key=lambda row: (row[0], row[3]))
    quantity = Decimal("0")
    bags = 0
    for _date, row_qty, row_bags, _pk in rows:
        quantity += row_qty
        if quantity < 0:
            raise ValidationError("Операция создаёт отрицательный остаток на складе.")
        if row_bags is not None:
            bags += row_bags
            if bags < 0:
                raise ValidationError("Операция создаёт отрицательный остаток мешков.")


def ensure_default_location(warehouse):
    from apps.inventory.models import DEFAULT_LOCATION_NAME, StorageLocation

    location = StorageLocation.objects.filter(warehouse=warehouse, name=DEFAULT_LOCATION_NAME).order_by("pk").first()
    if location is None:
        location = StorageLocation.objects.create(warehouse=warehouse, name=DEFAULT_LOCATION_NAME, active=True)
    elif not location.active:
        location.active = True
        location.save(update_fields=["active"])
    return location


def resolve_location(warehouse, location=None):
    if location is None:
        return ensure_default_location(warehouse)
    if location.warehouse_id != warehouse.id:
        raise ValidationError("Место хранения не относится к выбранному складу.")
    return location


def add_stock(document, product, location, qty_delta, bags_delta):
    assert_stock(location.id, product.id, document.effective_date, qty_delta, bags_delta)
    return StockMove.objects.create(
        document=document,
        product=product,
        location=location,
        qty_delta=qty_delta,
        bags_delta=bags_delta,
        unit_code=product.unit,
        unit_weight_kg=product.unit_weight_kg,
        effective_date=document.effective_date,
    )


def assert_receipt_channel(purchase_line, *, via_shipment):
    """One purchase line is received either by posted shipments or by manual receipts."""
    from apps.procurement.models import Shipment

    posted = ReceiptLine.objects.filter(
        purchase_line_id=purchase_line.pk,
        receipt__document__state=Document.State.POSTED,
        receipt__document__reversal__isnull=True,
    )
    if via_shipment:
        if posted.filter(receipt__source_shipment__isnull=True).exists():
            raise ValidationError(
                "По этой строке уже есть проведённая ручная приёмка. "
                "Проведение поставки создаст второй остаток и второй долг. Сначала отмените ручные приёмки."
            )
        return
    if posted.filter(
        receipt__source_shipment__isnull=False,
        receipt__source_shipment__status=Shipment.State.POSTED,
    ).exists():
        raise ValidationError(
            "По этой строке товар уже принят проведением поставки. "
            "Отдельная приёмка создаст второй остаток и второй долг."
        )


@transaction.atomic
def record_receipt(*, supplier, warehouse, effective_date, lines, note="", actor=None, via_shipment=False):
    from collections import defaultdict

    from apps.core.models import Party
    from apps.finance.models import OpenItem
    from apps.finance.services import add_open_item, apply_supplier_advances
    from apps.procurement.models import PurchaseLine, PurchaseOrder

    if not lines:
        raise ValidationError("В приёмке нужна хотя бы одна строка.")
    require_active(supplier)
    require_active(warehouse)
    Party.objects.select_for_update().get(pk=supplier.pk)
    claimed = defaultdict(lambda: Decimal("0"))
    prepared = []
    for row in lines:
        product = row["product"]
        location = resolve_location(warehouse, row.get("location"))
        require_active(product)
        require_active(location)
        quantity = q_qty(row["quantity"])
        if quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        purchase_line = row.get("purchase_line")
        if purchase_line is None:
            raise ValidationError("Приёмка поставщика ссылается на строку закупки.")
        claimed[purchase_line.pk] += quantity
        prepared.append((product, location, quantity, row.get("bags"), purchase_line))
    order_ids = sorted({line.order_id for *_rest, line in prepared})
    list(PurchaseOrder.objects.select_for_update().filter(pk__in=order_ids).order_by("pk"))
    locked = {
        row.pk: row
        for row in PurchaseLine.objects.select_related("order__document", "product")
        .select_for_update(of=("self",))
        .filter(pk__in=sorted(claimed))
        .order_by("pk")
    }
    if len(locked) != len(claimed):
        raise ValidationError("Строка закупки не найдена.")
    currencies = set()
    totals = defaultdict(lambda: Decimal("0"))
    for line_id, extra in claimed.items():
        purchase_line = locked[line_id]
        order = purchase_line.order
        if order.document.state != Document.State.POSTED:
            raise ValidationError("Приёмка ссылается на непроведённую закупку.")
        if getattr(order, "operational_status", "IN_PROGRESS") == "COMPLETED":
            raise ValidationError("Спецификация выполнена. Сначала верните её в работу.")
        assert_receipt_channel(purchase_line, via_shipment=via_shipment)
        if order.supplier_id != supplier.pk:
            raise ValidationError("Поставщик приёмки и закупки должен совпадать.")
        currencies.add(order.currency)
        totals[order.pk] += line_amount(extra, purchase_line.price)
    if len(currencies) > 1:
        raise ValidationError("Одна приёмка не смешивает валюты закупки.")
    document = draft_document(Document.Kind.RECEIPT, effective_date, note, actor)
    receipt = GoodsReceipt.objects.create(document=document, supplier=supplier, warehouse=warehouse)
    for product, location, quantity, bags, purchase_line in prepared:
        ReceiptLine.objects.create(
            receipt=receipt,
            product=product,
            location=location,
            purchase_line=purchase_line,
            quantity=quantity,
            bags=bags,
        )
    lock_positions((location.id, product.id) for product, location, _quantity, _bags, _line in prepared)
    for product, location, quantity, bags, _line in prepared:
        add_stock(document, product, location, quantity, bags)
    orders = {row.order_id: row.order for row in locked.values()}
    for order_id, amount in totals.items():
        order = orders[order_id]
        label = order.document.number
        if order.specification_number:
            label = f"{label}, спецификация {order.specification_number}"
        add_open_item(
            document,
            supplier,
            OpenItem.Side.WE_OWE,
            OpenItem.Lane.PAYABLE,
            amount,
            f"Приёмка {document.number} по {label}",
            order=order,
            currency=order.currency,
        )
    deal_currency = next(iter(currencies))
    apply_supplier_advances(document, supplier, deal_currency)
    post_document(
        document,
        snapshot={
            "via_shipment": via_shipment,
            "warehouse": warehouse.code,
            "lines": [
                {"product": product.sku, "quantity": quantity, "purchase_line": purchase_line.pk}
                for product, _location, quantity, _bags, purchase_line in prepared
            ],
            "payables": [
                {
                    "order": orders[order_id].document.number,
                    "amount": amount,
                    "currency": orders[order_id].currency,
                }
                for order_id, amount in totals.items()
            ],
        },
    )
    return receipt


@transaction.atomic
def record_issue(*, customer, warehouse, effective_date, lines, note="", actor=None):
    from collections import defaultdict

    from apps.sales.models import SaleLine

    if not lines:
        raise ValidationError("В выдаче нужна хотя бы одна строка.")
    require_active(customer)
    require_active(warehouse)
    claimed_qty = defaultdict(lambda: Decimal("0"))
    claimed_bags = defaultdict(int)
    prepared = []
    for row in lines:
        product = row["product"]
        location = resolve_location(warehouse, row.get("location"))
        require_active(product)
        require_active(location)
        quantity = q_qty(row["quantity"])
        bags = row.get("bags")
        if quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        sale_line = row.get("sale_line")
        if sale_line is not None:
            claimed_qty[sale_line.pk] += quantity
            if bags:
                claimed_bags[sale_line.pk] += bags
        prepared.append((product, location, quantity, bags, sale_line))
    for line_id, extra in claimed_qty.items():
        sale_line = SaleLine.objects.get(pk=line_id)
        already = (
            IssueLine.objects.filter(sale_line=sale_line, issue__document__state=Document.State.POSTED).aggregate(
                total=Sum("quantity")
            )["total"]
            or Decimal("0")
        )
        if already + extra > sale_line.quantity:
            raise ValidationError("Выдача больше проданного количества.")
        extra_bags = claimed_bags[line_id]
        if sale_line.bags is not None and extra_bags:
            issued_bags = (
                IssueLine.objects.filter(sale_line=sale_line, issue__document__state=Document.State.POSTED).aggregate(
                    total=Sum("bags")
                )["total"]
                or 0
            )
            if issued_bags + extra_bags > sale_line.bags:
                raise ValidationError("Выдача больше проданного числа мешков.")
    document = draft_document(Document.Kind.ISSUE, effective_date, note, actor)
    issue = GoodsIssue.objects.create(document=document, customer=customer, warehouse=warehouse)
    for product, location, quantity, bags, sale_line in prepared:
        IssueLine.objects.create(
            issue=issue, product=product, location=location, sale_line=sale_line, quantity=quantity, bags=bags
        )
    lock_positions((location.id, product.id) for product, location, _quantity, _bags, _line in prepared)
    for product, location, quantity, bags, _line in prepared:
        add_stock(document, product, location, -quantity, None if bags is None else -bags)
    post_document(
        document,
        snapshot={
            "warehouse": warehouse.code,
            "lines": [
                {"product": product.sku, "quantity": quantity}
                for product, _location, quantity, _bags, _sale_line in prepared
            ],
        },
    )
    return issue


@transaction.atomic
def repost_receipt(receipt, *, actor=None):
    from apps.core.models import Party
    from apps.finance.models import OpenItem
    from apps.finance.services import add_open_item
    from apps.procurement.models import PurchaseLine, Shipment

    document = Document.objects.select_for_update().get(pk=receipt.document_id)
    if document.state != Document.State.DRAFT:
        raise ValidationError("Повторно провести можно только черновик приёмки.")
    if Shipment.objects.filter(receipt=receipt).exists():
        raise ValidationError("Эта приёмка создана поставкой. Проведите саму поставку.")
    if document.stock_moves.exists() or document.open_items.exists():
        raise ValidationError("У черновика уже есть проводки.")
    lines = list(receipt.lines.select_related("product", "location", "purchase_line__order__document"))
    if not lines:
        raise ValidationError("В приёмке нет строк.")
    line_ids = sorted({line.purchase_line_id for line in lines if line.purchase_line_id})
    locked = {
        row.pk: row
        for row in PurchaseLine.objects.select_for_update().filter(pk__in=line_ids).order_by("pk")
    }
    Party.objects.select_for_update().get(pk=receipt.supplier_id)
    totals = {}
    for line in lines:
        purchase_line = locked.get(line.purchase_line_id)
        if purchase_line is None:
            raise ValidationError("Строка закупки не найдена.")
        order = purchase_line.order
        if order.document.state != Document.State.POSTED:
            raise ValidationError("Приёмка ссылается на непроведённую закупку.")
        if order.operational_status == "COMPLETED":
            raise ValidationError("Спецификация выполнена. Сначала верните её в работу.")
        assert_receipt_channel(purchase_line, via_shipment=False)
        totals[order.pk] = totals.get(order.pk, Decimal("0")) + line_amount(line.quantity, purchase_line.price)
    lock_positions((line.location_id, line.product_id) for line in lines)
    for line in lines:
        add_stock(document, line.product, line.location, line.quantity, line.bags)
    orders = {row.order_id: row.order for row in locked.values()}
    for order_id, amount in totals.items():
        order = orders[order_id]
        add_open_item(
            document,
            receipt.supplier,
            OpenItem.Side.WE_OWE,
            OpenItem.Lane.PAYABLE,
            amount,
            f"Приёмка {document.number} по {order.document.number}",
            order=order,
            currency=order.currency,
        )
    post_document(document, snapshot={"repost": True, "payables": {str(key): amount for key, amount in totals.items()}})
    return receipt


@transaction.atomic
def repost_issue(issue, *, actor=None):
    from apps.sales.models import SaleLine

    document = Document.objects.select_for_update().get(pk=issue.document_id)
    if document.state != Document.State.DRAFT:
        raise ValidationError("Повторно провести можно только черновик выдачи.")
    if document.stock_moves.exists():
        raise ValidationError("У черновика уже есть движения.")
    lines = list(issue.lines.select_related("product", "location", "sale_line"))
    if not lines:
        raise ValidationError("В выдаче нет строк.")
    for line in lines:
        if line.sale_line_id is None:
            continue
        sale_line = SaleLine.objects.select_for_update().get(pk=line.sale_line_id)
        already = (
            IssueLine.objects.filter(sale_line=sale_line, issue__document__state=Document.State.POSTED).aggregate(
                total=Sum("quantity")
            )["total"]
            or Decimal("0")
        )
        if already + line.quantity > sale_line.quantity:
            raise ValidationError("Выдача больше проданного количества.")
    lock_positions((line.location_id, line.product_id) for line in lines)
    for line in lines:
        add_stock(document, line.product, line.location, -line.quantity, None if line.bags is None else -line.bags)
    post_document(document, snapshot={"repost": True})
    return issue
