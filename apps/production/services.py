from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import Document
from apps.core.quantities import q_qty
from apps.core.services import draft_document, post_document, require_active
from apps.inventory.checks import sack_pieces
from apps.inventory.models import Product
from apps.inventory.services import add_stock, lock_positions, resolve_location
from apps.production.models import InputLine, OutputLine, ProductionReport


def _place(row, product, location_key, warehouse_key):
    location = row.get(location_key)
    warehouse = row.get(warehouse_key)
    if location is None:
        if warehouse is None:
            raise ValidationError("Укажите склад.")
        location = resolve_location(warehouse)
    elif warehouse is not None and location.warehouse_id != warehouse.pk:
        raise ValidationError("Место хранения не относится к выбранному складу.")
    require_active(location)
    require_active(product)
    return location


def _stock_bags(product, bags):
    if product.unit == Product.Unit.BAG:
        return None
    return bags


def _apply_production(document, outputs, inputs):
    prepared = []
    pairs = []
    for product, location, packaging, quantity, bags in outputs:
        pieces = sack_pieces(product, quantity, bags)
        prepared.append((product, location, packaging, quantity, bags, pieces))
        pairs.append((location.id, product.id))
        if pieces and packaging is not None:
            pairs.append((packaging.id, product.sack_id))
    for product, location, quantity in inputs:
        pairs.append((location.id, product.id))
    lock_positions(pairs)
    for product, location, packaging, quantity, bags, pieces in prepared:
        add_stock(document, product, location, quantity, _stock_bags(product, bags))
        if pieces and packaging is not None:
            add_stock(document, product.sack, packaging, Decimal(-pieces), None)
    for product, location, quantity in inputs:
        add_stock(document, product, location, -quantity, None)


@transaction.atomic
def record_production(*, effective_date, outputs, inputs=(), note="", actor=None):
    if not outputs:
        raise ValidationError("В выпуске нужна хотя бы одна строка продукции.")
    prepared_outputs = []
    for row in outputs:
        product = row["product"]
        require_active(product)
        quantity = q_qty(row["quantity"])
        if quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        location = _place(row, product, "location", "warehouse")
        pieces = sack_pieces(product, quantity, row.get("bags"))
        packaging = None
        if pieces:
            packaging = _place(row, product.sack, "packaging_location", "packaging_warehouse")
        elif row.get("packaging_location") is not None or row.get("packaging_warehouse") is not None:
            raise ValidationError("Место мешков указывается, когда для муки задан пустой мешок.")
        prepared_outputs.append((product, location, packaging, quantity, row.get("bags")))
    prepared_inputs = []
    for row in inputs:
        product = row["product"]
        require_active(product)
        quantity = q_qty(row["quantity"])
        if quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        location = _place(row, product, "location", "warehouse")
        prepared_inputs.append((product, location, quantity))
    document = draft_document(Document.Kind.PRODUCTION, effective_date, note, actor)
    report = ProductionReport.objects.create(document=document)
    for product, location, packaging, quantity, bags in prepared_outputs:
        OutputLine.objects.create(
            report=report,
            product=product,
            location=location,
            packaging_location=packaging,
            quantity=quantity,
            bags=bags,
        )
    for product, location, quantity in prepared_inputs:
        InputLine.objects.create(report=report, product=product, location=location, quantity=quantity)
    _apply_production(document, prepared_outputs, prepared_inputs)
    post_document(
        document,
        snapshot={
            "outputs": [
                {"product": product.sku, "quantity": quantity, "bags": bags}
                for product, _location, _packaging, quantity, bags in prepared_outputs
            ],
            "inputs": [
                {"product": product.sku, "quantity": quantity} for product, _location, quantity in prepared_inputs
            ],
        },
    )
    return report


@transaction.atomic
def repost_production(report, *, actor=None):
    document = Document.objects.select_for_update().get(pk=report.document_id)
    if document.state != Document.State.DRAFT:
        raise ValidationError("Повторно провести можно только черновик выпуска.")
    if document.stock_moves.exists():
        raise ValidationError("У черновика уже есть движения.")
    outputs = [
        (line.product, line.location, line.packaging_location, line.quantity, line.bags)
        for line in report.outputs.select_related("product", "product__sack", "location", "packaging_location")
    ]
    inputs = [
        (line.product, line.location, line.quantity)
        for line in report.inputs.select_related("product", "location")
    ]
    if not outputs:
        raise ValidationError("В выпуске нужна хотя бы одна строка продукции.")
    _apply_production(document, outputs, inputs)
    post_document(document, snapshot={"repost": True})
    return report
