from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.audit import write_audit
from apps.core.models import AuditEntry, Document, Party
from apps.core.posting import delete_draft_document, unpost_document
from apps.core.quantities import line_amount, q_qty
from apps.core.services import commercial_lines, draft_document, post_document, require_active
from apps.inventory.models import Product, Warehouse
from apps.inventory.services import record_receipt
from apps.procurement.models import (
    DeliveryTerm,
    PurchaseContract,
    PurchaseLine,
    PurchaseOrder,
    RailwayStation,
    Shipment,
    ShipmentWagon,
)


def _code(model, name, fallback):
    raw = "".join(ch for ch in (name or "").upper() if ch.isalnum())
    base = (raw[:16] or fallback)
    code = base
    number = 2
    while model.objects.filter(code=code).exists():
        code = f"{base[:12]}-{number}"
        number += 1
        if number > 1000:
            raise ValidationError("Не удалось подобрать код.")
    return code


@transaction.atomic
def save_delivery_term(*, name, code="", description="", active=True, term=None, actor=None):
    name = (name or "").strip()
    if not name:
        raise ValidationError("Укажите название условия поставки.")
    if term is None:
        term = DeliveryTerm(code=(code or "").strip() or _code(DeliveryTerm, name, "TERM"), name=name)
    else:
        term = DeliveryTerm.objects.select_for_update().get(pk=term.pk)
        if code:
            term.code = code.strip()
    term.name = name
    term.description = description or ""
    term.active = active
    term.save()
    write_audit(
        action=AuditEntry.Action.UPDATED if term.pk else AuditEntry.Action.CREATED,
        actor=actor,
        target_type="delivery_term",
        target_id=term.pk,
        detail=term.name,
    )
    return term


@transaction.atomic
def save_station(*, name, station_code="", country="", active=True, station=None, actor=None):
    if station is None:
        station = RailwayStation(name=name, station_code=station_code or "", country=country or "", active=active)
    else:
        station = RailwayStation.objects.select_for_update().get(pk=station.pk)
        station.name = name
        station.station_code = station_code or ""
        station.country = country or ""
        station.active = active
    station.save()
    write_audit(
        action=AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="railway_station",
        target_id=station.pk,
        detail=station.name,
    )
    return station


@transaction.atomic
def record_contract(
    *,
    supplier,
    number,
    contract_date,
    description="",
    active=True,
    currency=PurchaseOrder.Currency.KGS,
    delivery_term=None,
):
    require_active(supplier)
    if delivery_term is not None:
        require_active(delivery_term)
    return PurchaseContract.objects.create(
        supplier=supplier,
        number=number,
        contract_date=contract_date,
        description=description,
        active=active,
        currency=currency,
        delivery_term=delivery_term,
    )


def _open_for_shipments(order):
    if order.operational_status == PurchaseOrder.OperationalStatus.COMPLETED:
        raise ValidationError("Спецификация выполнена. Сначала верните её в работу.")


@transaction.atomic
def record_purchase(
    *,
    supplier,
    effective_date,
    lines,
    note="",
    actor=None,
    contract=None,
    specification_number="",
    currency=None,
    delivery_term=None,
    tolerance_percent=Decimal("10"),
):
    require_active(supplier)
    Party.objects.select_for_update().get(pk=supplier.pk)
    if contract is not None:
        require_active(contract)
        PurchaseContract.objects.select_for_update().get(pk=contract.pk)
        if contract.supplier_id != supplier.pk:
            raise ValidationError("Поставщик закупки должен совпадать с поставщиком договора.")
        if currency is None:
            currency = contract.currency
        if delivery_term is None:
            delivery_term = contract.delivery_term
    if currency is None:
        currency = PurchaseOrder.Currency.KGS
    currency = str(currency).upper()
    if currency not in PurchaseOrder.Currency.values:
        raise ValidationError("Валюта закупки должна быть KGS, RUB, USD или KZT.")
    if delivery_term is not None:
        require_active(delivery_term)
    prepared = commercial_lines(lines)
    document = draft_document(Document.Kind.PURCHASE, effective_date, note, actor)
    order = PurchaseOrder.objects.create(
        document=document,
        supplier=supplier,
        contract=contract,
        specification_number=specification_number,
        currency=currency,
        delivery_term=delivery_term,
        tolerance_percent=tolerance_percent,
    )
    for product, quantity, price, bags, amount in prepared:
        PurchaseLine.objects.create(
            order=order, product=product, quantity=quantity, price=price, amount=amount, bags=bags
        )
    post_document(document)
    return order


@transaction.atomic
def update_specification(
    order,
    *,
    lines=None,
    tolerance_percent=None,
    delivery_term=None,
    specification_number=None,
    currency=None,
    actor=None,
):
    from apps.inventory.models import ReceiptLine

    order = PurchaseOrder.objects.select_for_update().select_related("document").get(pk=order.pk)
    structural = lines is not None or specification_number is not None or currency is not None
    if structural:
        posted_receipt = ReceiptLine.objects.filter(
            purchase_line__order=order,
            receipt__document__state=Document.State.POSTED,
        ).exists()
        if posted_receipt or order.shipments.filter(status=Shipment.State.POSTED).exists():
            raise ValidationError("Есть проведённые поставки или приёмки. Сначала отмените их выполнение.")
        unpost_document(order.document, actor=actor)
        order.document.refresh_from_db()
        if specification_number is not None:
            order.specification_number = specification_number
        if currency is not None:
            order.currency = str(currency).upper()
        order.save()
        if lines is not None:
            PurchaseLine.objects.filter(order=order).delete()
            for product, quantity, price, bags, amount in commercial_lines(lines):
                PurchaseLine.objects.create(
                    order=order, product=product, quantity=quantity, price=price, amount=amount, bags=bags
                )
        post_document(order.document)
    if tolerance_percent is not None:
        order.tolerance_percent = tolerance_percent
    if delivery_term is not None:
        require_active(delivery_term)
        order.delivery_term = delivery_term
    if tolerance_percent is not None or delivery_term is not None:
        order.save()
    write_audit(
        action=AuditEntry.Action.UPDATED,
        document=order.document,
        actor=actor,
        detail="Спецификация изменена.",
    )
    return order


@transaction.atomic
def delete_specification(order, *, actor=None):
    """Remove a contract specification that has not moved stock or debt."""
    from apps.inventory.models import ReceiptLine

    order = PurchaseOrder.objects.select_for_update().select_related("document").get(pk=order.pk)
    if not order.contract_id:
        raise ValidationError("Удаляется спецификация по договору.")
    posted_receipt = ReceiptLine.objects.filter(
        purchase_line__order=order,
        receipt__document__state=Document.State.POSTED,
    ).exists()
    if posted_receipt or order.shipments.filter(status=Shipment.State.POSTED).exists():
        raise ValidationError("Есть проведённые поставки или приёмки. Сначала отмените их выполнение.")
    if order.shipments.exists():
        raise ValidationError("Сначала удалите поставки этой спецификации.")
    if order.expenses.exists():
        raise ValidationError("Сначала отвяжите расходы от этой спецификации.")
    if order.open_items.exists():
        raise ValidationError("По спецификации есть долг. Сначала отмените связанные приёмки.")
    if ReceiptLine.objects.filter(purchase_line__order=order).exists():
        raise ValidationError("По спецификации есть приёмка. Сначала отмените и удалите её.")
    document = order.document
    if document.state == Document.State.POSTED:
        unpost_document(document, actor=actor, detail="Спецификация удаляется.")
    delete_draft_document(document, actor=actor)


@transaction.atomic
def complete_specification(order, *, actor=None):
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    order.operational_status = PurchaseOrder.OperationalStatus.COMPLETED
    order.save(update_fields=["operational_status"])
    write_audit(
        action=AuditEntry.Action.UPDATED,
        document=order.document,
        actor=actor,
        detail="Спецификация отмечена выполненной. Движения не менялись.",
    )
    return order


@transaction.atomic
def reopen_specification(order, *, actor=None):
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    order.operational_status = PurchaseOrder.OperationalStatus.IN_PROGRESS
    order.save(update_fields=["operational_status"])
    write_audit(
        action=AuditEntry.Action.UPDATED,
        document=order.document,
        actor=actor,
        detail="Спецификация возвращена в работу. Движения не менялись.",
    )
    return order


def _require_station(station):
    if station is None:
        raise ValidationError("Укажите станцию отправления.")
    require_active(station)
    if not isinstance(station, RailwayStation):
        station = RailwayStation.objects.get(pk=station)
        require_active(station)
    return station


def _shipment_values(shipment):
    station = shipment.departure_station
    order = shipment.order
    return {
        "specification": order.document.number,
        "quantity": shipment.quantity,
        "wagon_count": shipment.wagon_count,
        "departure_date": shipment.departure_date,
        "arrival_date": shipment.arrival_date,
        "station": None if station is None else station.name,
        "currency": order.currency,
    }


@transaction.atomic
def record_shipment(
    *,
    order,
    quantity,
    departure_date=None,
    wagon_number="",
    arrival_date=None,
    notes="",
    departure_station=None,
    wagon_count=None,
    actor=None,
):
    quantity = q_qty(quantity)
    if quantity <= 0:
        raise ValidationError("Вес поставки должен быть больше нуля.")
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    _open_for_shipments(order)
    station = _require_station(departure_station)
    count = wagon_count if wagon_count is not None else 1
    if count < 1:
        raise ValidationError("Число вагонов должно быть больше нуля.")
    shipment = Shipment.objects.create(
        order=order,
        departure_station=station,
        quantity=quantity,
        departure_date=departure_date,
        arrival_date=arrival_date,
        notes=notes or "",
        wagon_count=count,
        status=Shipment.State.DRAFT,
    )
    number = (wagon_number or "").strip()
    if number:
        ShipmentWagon.objects.create(shipment=shipment, wagon_number=number, weight_kg=quantity)
        shipment.details_complete = count == 1
        shipment.save(update_fields=["details_complete"])
    write_audit(
        action=AuditEntry.Action.CREATED,
        actor=actor,
        target_type="shipment",
        target_id=shipment.pk,
        detail=f"Черновик поставки по {order.document.number}.",
        snapshot=_shipment_values(shipment),
    )
    return shipment


@transaction.atomic
def update_shipment(
    shipment,
    *,
    status=None,
    arrival_date=None,
    notes=None,
    departure_date=None,
    departure_station=None,
    quantity=None,
    wagon_count=None,
    order=None,
    actor=None,
):
    current = (
        Shipment.objects.select_for_update(of=("self",))
        .select_related("order__document", "departure_station")
        .get(pk=shipment.pk)
    )
    previous = _shipment_values(current)
    if status is not None:
        raise ValidationError("Статус пути больше не используется. Проведите поставку или отмените выполнение.")
    if current.status == Shipment.State.POSTED:
        blocked = []
        if quantity is not None and q_qty(quantity) != current.quantity:
            blocked.append("вес")
        if wagon_count is not None and wagon_count != current.wagon_count:
            blocked.append("число вагонов")
        if order is not None and order.pk != current.order_id:
            blocked.append("спецификацию")
        if arrival_date is not None and arrival_date != current.arrival_date:
            blocked.append("дату приёмки")
        if blocked:
            raise ValidationError(
                "Чтобы изменить " + ", ".join(blocked) + ", сначала отмените выполнение поставки."
            )
    if departure_station is not None:
        current.departure_station = _require_station(departure_station)
    if departure_date is not None:
        current.departure_date = departure_date
    if arrival_date is not None:
        current.arrival_date = arrival_date
    if notes is not None:
        current.notes = notes
    if order is not None and current.status == Shipment.State.DRAFT:
        _open_for_shipments(order)
        current.order = order
    if quantity is not None and current.status == Shipment.State.DRAFT:
        current.quantity = q_qty(quantity)
        current.details_complete = False
    if wagon_count is not None and current.status == Shipment.State.DRAFT:
        if wagon_count < 1:
            raise ValidationError("Число вагонов должно быть больше нуля.")
        current.wagon_count = wagon_count
        current.details_complete = False
    current.save()
    write_audit(
        action=AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="shipment",
        target_id=current.pk,
        detail="Поставка изменена.",
        snapshot={"previous": previous, "new": _shipment_values(current)},
    )
    return current


def _prepare_wagons(rows):
    prepared = []
    seen = set()
    for row in rows:
        number = (row.get("wagon_number") or "").strip()
        if not number:
            raise ValidationError("Укажите номер вагона.")
        weight = q_qty(row.get("weight_kg"))
        if weight <= 0:
            raise ValidationError("Вес вагона должен быть больше нуля.")
        if number in seen:
            raise ValidationError(f"Номер вагона {number} повторяется в поставке.")
        seen.add(number)
        prepared.append((number, weight))
    return prepared


@transaction.atomic
def declare_wagons(shipment, wagons, *, complete=False, actor=None):
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
    prepared = _prepare_wagons(wagons)
    if complete:
        total = sum((weight for _number, weight in prepared), Decimal("0"))
        if len(prepared) != shipment.wagon_count:
            raise ValidationError("Число вагонов не совпадает с заголовком поставки.")
        if q_qty(total) != shipment.quantity:
            raise ValidationError("Сумма веса вагонов не совпадает с весом поставки.")
    elif shipment.status == Shipment.State.POSTED and prepared:
        total = sum((weight for _number, weight in prepared), Decimal("0"))
        if len(prepared) == shipment.wagon_count and q_qty(total) == shipment.quantity:
            complete = True
    ShipmentWagon.objects.filter(shipment=shipment).delete()
    for number, weight in prepared:
        ShipmentWagon.objects.create(shipment=shipment, wagon_number=number, weight_kg=weight)
    shipment.details_complete = bool(complete and prepared)
    shipment.save(update_fields=["details_complete"])
    write_audit(
        action=AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="shipment",
        target_id=shipment.pk,
        detail="Вагоны поставки обновлены без изменения проведённого веса."
        if shipment.status == Shipment.State.POSTED
        else "Вагоны поставки обновлены.",
    )
    return shipment


@transaction.atomic
def remove_wagon(wagon, *, actor=None):
    wagon = ShipmentWagon.objects.select_related("shipment").get(pk=wagon.pk)
    shipment = Shipment.objects.select_for_update().get(pk=wagon.shipment_id)
    wagon.delete()
    shipment.details_complete = False
    shipment.save(update_fields=["details_complete"])
    write_audit(
        action=AuditEntry.Action.UPDATED,
        actor=actor,
        target_type="shipment",
        target_id=shipment.pk,
        detail=f"Удалён вагон {wagon.wagon_number}.",
    )
    return shipment


def specification_line(order):
    lines = list(order.lines.select_related("product"))
    if len(lines) != 1:
        raise ValidationError("Проведение поставки поддерживает спецификацию с одним товаром.")
    return lines[0]


def receipt_quantity(product, weight_kg):
    weight_kg = q_qty(weight_kg)
    if product.unit == Product.Unit.KG:
        return weight_kg
    if product.unit_weight_kg and product.unit_weight_kg > 0:
        raw = weight_kg / product.unit_weight_kg
        quantity = q_qty(raw)
        if q_qty(quantity * product.unit_weight_kg) != weight_kg:
            raise ValidationError("Вес поставки не делится на массу одной единицы товара без остатка.")
        return quantity
    raise ValidationError("Нельзя перевести вес поставки в единицу товара: масса единицы не задана.")


def _bags_for(product, quantity):
    if product.unit == Product.Unit.KG and product.package_kg:
        if quantity % product.package_kg != 0:
            raise ValidationError("Масса поставки не кратна массе мешка.")
        return int(quantity / product.package_kg)
    return None


def resolve_warehouse(product, warehouse=None):
    if warehouse is not None:
        require_active(warehouse)
        return warehouse
    rows = list(Warehouse.objects.filter(active=True).order_by("pk"))
    exact = [row for row in rows if row.category_id == product.category_id]
    pool = exact or [row for row in rows if row.category_id is None]
    if not pool:
        raise ValidationError("Нет склада для категории этого товара.")
    if len(pool) == 1:
        return pool[0]
    raise ValidationError("Укажите склад: подходящих складов несколько.")


def _wagons_ready(shipment):
    wagons = list(shipment.wagons.all())
    if not wagons:
        return
    if not shipment.details_complete:
        raise ValidationError(
            "Детализация вагонов не завершена. Завершите её или удалите строки вагонов перед проведением."
        )
    numbers = [wagon.wagon_number for wagon in wagons]
    if len(numbers) != len(set(numbers)):
        raise ValidationError("Номер вагона повторяется в поставке.")
    if len(wagons) != shipment.wagon_count:
        raise ValidationError("Число вагонов не совпадает с заголовком поставки.")
    total = sum((wagon.weight_kg for wagon in wagons), Decimal("0"))
    if q_qty(total) != shipment.quantity:
        raise ValidationError("Сумма веса вагонов не совпадает с весом поставки.")


@transaction.atomic
def post_shipment(shipment, *, warehouse=None, actor=None):
    shipment = (
        Shipment.objects.select_for_update(of=("self",))
        .select_related("order__document", "order__supplier", "departure_station", "receipt__document")
        .get(pk=shipment.pk)
    )
    if shipment.status == Shipment.State.POSTED:
        return shipment
    Party.objects.select_for_update().get(pk=shipment.order.supplier_id)
    order = PurchaseOrder.objects.select_for_update().get(pk=shipment.order_id)
    _open_for_shipments(order)
    if shipment.departure_station_id is None:
        raise ValidationError("Укажите станцию отправления.")
    if not shipment.departure_station.active:
        raise ValidationError("Станция отправления отключена.")
    if shipment.arrival_date is None:
        raise ValidationError("Укажите дату приёмки. Дата отправления не подставляется.")
    _wagons_ready(shipment)
    line = specification_line(order)
    product = line.product
    require_active(product)
    quantity = receipt_quantity(product, shipment.quantity)
    warehouse = resolve_warehouse(product, warehouse)
    receipt = record_receipt(
        supplier=order.supplier,
        warehouse=warehouse,
        effective_date=shipment.arrival_date,
        lines=[
            {
                "product": product,
                "quantity": quantity,
                "purchase_line": line,
                "bags": _bags_for(product, quantity),
            }
        ],
        note=f"Поставка {shipment.pk}",
        actor=actor,
        via_shipment=True,
    )
    shipment.receipt = receipt
    shipment.status = Shipment.State.POSTED
    shipment.posted_at = timezone.now()
    shipment.save(update_fields=["receipt", "status", "posted_at"])
    write_audit(
        action=AuditEntry.Action.POSTED,
        document=receipt.document,
        actor=actor,
        target_type="shipment",
        target_id=shipment.pk,
        detail=f"Поставка проведена: склад +{quantity} {product.get_unit_display()}, долг по цене спецификации.",
        snapshot={
            **_shipment_values(shipment),
            "product": product.sku,
            "price": line.price,
            "payable": line_amount(quantity, line.price),
            "warehouse": warehouse.code,
            "stock_quantity": quantity,
            "unit": product.unit,
        },
    )
    return shipment


@transaction.atomic
def unpost_shipment(shipment, *, actor=None):
    from apps.core.posting import ledger_snapshot

    shipment = (
        Shipment.objects.select_for_update(of=("self",))
        .select_related("receipt__document", "order__document", "departure_station")
        .get(pk=shipment.pk)
    )
    if shipment.status != Shipment.State.POSTED:
        raise ValidationError("Отменить выполнение можно только у проведённой поставки.")
    receipt = shipment.receipt
    line = shipment.order.lines.select_related("product").first()
    snapshot = {"business": _shipment_values(shipment)}
    if line is not None:
        snapshot["business"]["product"] = line.product.sku
        snapshot["business"]["price"] = line.price
        snapshot["business"]["currency"] = shipment.order.currency
    if receipt is not None:
        snapshot.update(ledger_snapshot(receipt.document))
        payable = next((item["amount"] for item in snapshot["open_items"] if item["side"] == "WE_OWE"), None)
        snapshot["business"]["payable"] = payable
    shipment.receipt = None
    shipment.status = Shipment.State.DRAFT
    shipment.posted_at = None
    shipment.save(update_fields=["receipt", "status", "posted_at"])
    if receipt is not None:
        unpost_document(receipt.document, actor=actor, detail=f"Отмена поставки {shipment.pk}.")
        delete_draft_document(receipt.document, actor=actor)
    write_audit(
        action=AuditEntry.Action.UNPOSTED,
        actor=actor,
        target_type="shipment",
        target_id=shipment.pk,
        number=receipt.document.number if receipt is not None else "",
        kind=Document.Kind.RECEIPT,
        detail="Выполнение поставки отменено. Склад и долг этой поставки сняты.",
        snapshot=snapshot,
    )
    return shipment


@transaction.atomic
def delete_shipment(shipment, *, actor=None):
    shipment = (
        Shipment.objects.select_for_update(of=("self",))
        .select_related("order__document", "departure_station")
        .get(pk=shipment.pk)
    )
    if shipment.status != Shipment.State.DRAFT:
        raise ValidationError("Проведённую поставку нельзя удалить. Сначала отмените выполнение.")
    if shipment.expenses.exists():
        raise ValidationError("Сначала отвяжите расходы от этой поставки.")
    write_audit(
        action=AuditEntry.Action.DELETED,
        actor=actor,
        target_type="shipment",
        target_id=shipment.pk,
        detail="Черновик поставки удалён.",
        snapshot=_shipment_values(shipment),
    )
    ShipmentWagon.objects.filter(shipment=shipment).delete()
    shipment.delete()
