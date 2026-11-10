from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.catalog.models import OriginStation, Product, Supplier
from apps.procurement.models import (
    ContractLine,
    ContractPayment,
    ContractShipment,
    FactoryArrival,
    SupplyContract,
)

MONEY = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(MONEY)


def _reference(company, name, model, field):
    base = name.strip()[:40] or "запись"
    candidate = base
    number = 2
    while model.objects.filter(company=company, **{field: candidate}).exists():
        suffix = f"-{number}"
        candidate = f"{base[:40 - len(suffix)]}{suffix}"
        number += 1
    return candidate


@transaction.atomic
def create_counterparty(*, membership, actor, name, is_supplier, is_customer, is_other):
    if actor.pk != membership.user_id or not membership.allows("catalog.add_supplier"):
        raise PermissionDenied
    if not (is_supplier or is_customer or is_other):
        raise ValidationError("Нужна хотя бы одна роль: поставщик, покупатель или прочие.")
    return Supplier.objects.create(
        company=membership.company,
        name=name.strip(),
        reference=_reference(membership.company, name, Supplier, "reference"),
        is_supplier=is_supplier,
        is_customer=is_customer,
        is_other=is_other,
    )


@transaction.atomic
def create_station(*, membership, actor, name):
    if actor.pk != membership.user_id or not membership.allows("catalog.add_originstation"):
        raise PermissionDenied
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("Укажите станцию.")
    existing = OriginStation.objects.filter(company=membership.company, name=cleaned).first()
    if existing is not None:
        return existing
    return OriginStation.objects.create(company=membership.company, name=cleaned)


@transaction.atomic
def create_good(*, membership, actor, name, kind, unit, grade, package_kg):
    if actor.pk != membership.user_id or not membership.allows("catalog.add_product"):
        raise PermissionDenied
    return Product.objects.create(
        company=membership.company,
        sku=_reference(membership.company, name, Product, "sku"),
        name=name.strip(),
        kind=kind,
        unit=unit,
        grade=(grade or "").strip(),
        package_kg=package_kg,
    )


@transaction.atomic
def create_contract(*, membership, actor, supplier, number, lines, key):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_supplycontract"):
        raise PermissionDenied
    existing = SupplyContract.objects.filter(company=membership.company, key=key).first()
    if existing is not None:
        return existing
    if not lines:
        raise ValidationError("Добавьте хотя бы одну строку: товар, количество и цена.")
    contract = SupplyContract(
        company=membership.company,
        supplier=supplier,
        number=number.strip(),
        key=key,
        actor=actor,
    )
    try:
        contract.save()
        for position, line in enumerate(lines, start=1):
            ContractLine.objects.create(
                contract=contract,
                product=line["product"],
                quantity=line["quantity"],
                price=line["price"],
                position=position,
            )
    except ValidationError as exc:
        raise ValidationError("; ".join(exc.messages)) from exc
    return contract


@transaction.atomic
def add_shipment(*, membership, actor, line, station, wagon_count, quantity, key):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_contractshipment"):
        raise PermissionDenied
    existing = ContractShipment.objects.filter(key=key).select_related("line__contract").first()
    if existing is not None:
        if existing.line.contract.company_id != membership.company_id:
            raise PermissionDenied
        return existing
    if line.contract.company_id != membership.company_id:
        raise ValidationError("Строка относится к другому предприятию.")
    shipment = ContractShipment(
        line=line,
        station=station,
        wagon_count=wagon_count,
        quantity=quantity,
        key=key,
        actor=actor,
    )
    try:
        shipment.save()
    except ValidationError as exc:
        raise ValidationError("; ".join(exc.messages)) from exc
    return shipment


@transaction.atomic
def receive_at_factory(*, membership, actor, shipment, warehouse, arrived_on, key):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_factoryarrival"):
        raise PermissionDenied
    existing = FactoryArrival.objects.filter(key=key).select_related("shipment__line__contract").first()
    if existing is not None:
        if existing.shipment.line.contract.company_id != membership.company_id:
            raise PermissionDenied
        return existing
    if shipment.line.contract.company_id != membership.company_id:
        raise ValidationError("Отгрузка относится к другому предприятию.")
    if FactoryArrival.objects.filter(shipment=shipment).exists():
        raise ValidationError("Дата прибытия для этой отгрузки уже записана.")
    arrival = FactoryArrival(
        shipment=shipment,
        warehouse=warehouse,
        arrived_on=arrived_on,
        key=key,
        actor=actor,
    )
    try:
        arrival.save()
    except ValidationError as exc:
        raise ValidationError("; ".join(exc.messages)) from exc
    return arrival


@transaction.atomic
def add_contract_payment(*, membership, actor, contract, paid_on, amount, key):
    if actor.pk != membership.user_id or not membership.allows("procurement.add_contractpayment"):
        raise PermissionDenied
    existing = ContractPayment.objects.filter(key=key).select_related("contract").first()
    if existing is not None:
        if existing.contract.company_id != membership.company_id:
            raise PermissionDenied
        return existing
    if contract.company_id != membership.company_id:
        raise ValidationError("Контракт относится к другому предприятию.")
    return ContractPayment.objects.create(contract=contract, paid_on=paid_on, amount=money(amount), key=key, actor=actor)


def contract_position(contract):
    ordered_sum = Decimal("0")
    arrived_sum = Decimal("0")
    line_rows = []
    for line in contract.lines.all():
        ordered_sum += line.quantity * line.price
        arrived_qty = Decimal("0")
        for shipment in line.shipments.all():
            if getattr(shipment, "factory_arrival", None) is not None:
                arrived_qty += shipment.quantity
        arrived_sum += arrived_qty * line.price
        line_rows.append(
            {
                "line": line,
                "ordered_sum": money(line.quantity * line.price),
                "arrived_qty": arrived_qty,
                "remaining_qty": line.quantity - arrived_qty,
            }
        )
    paid = contract.bank_payments.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    arrived_sum = money(arrived_sum)
    paid = money(paid)
    return {
        "lines": line_rows,
        "ordered_sum": money(ordered_sum),
        "arrived_sum": arrived_sum,
        "paid": paid,
        "due": money(arrived_sum - paid),
    }
