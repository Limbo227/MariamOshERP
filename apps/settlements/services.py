from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.core.operations import existing_operation, finish_operation
from apps.procurement.models import PurchaseCharge
from apps.settlements.models import (
    ObligationEntry,
    PaymentAllocation,
    SupplierObligation,
    SupplierPayment,
)

MONEY = Decimal("0.01")
PAYMENT_COMMAND = "settlements.payment.record"


def money(value):
    return Decimal(value).quantize(MONEY)


def line_terms(line):
    latest = line.amendmentline_set.select_related("amendment").order_by("-amendment__revision").first()
    if latest is not None:
        return latest.new_quantity, latest.new_price
    return line.quantity, line.unit_price


def agreed_total(order):
    total = Decimal("0")
    for line in order.lines.all():
        quantity, price = line_terms(line)
        if price is None:
            raise ValidationError("Нет согласованной цены.")
        total += money(quantity * price)
    return total


def obligation_position(obligation):
    charges = obligation.entries.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    paid = obligation.allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    net = money(charges - paid)
    return {"charges": money(charges), "paid": money(paid), "due": max(net, Decimal("0")), "credit": max(-net, Decimal("0"))}


def unallocated_amount(payment):
    used = payment.allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return money(payment.amount - used)


@transaction.atomic
def open_order_obligation(*, order, actor):
    obligation, _created = SupplierObligation.objects.get_or_create(
        order=order,
        defaults={"company": order.company, "supplier": order.supplier, "currency": order.currency, "manual_reference": ""},
    )
    ObligationEntry.objects.create(
        obligation=obligation,
        amount=agreed_total(order),
        kind=ObligationEntry.Kind.INITIAL,
        source_key=f"order:{order.pk}",
        effective_date=order.effective_date,
        actor=actor,
    )
    return obligation


@transaction.atomic
def post_amendment_delta(*, order, amendment, actor, previous_total):
    obligation = order.supplierobligation
    delta = money(agreed_total(order) - previous_total)
    if delta == 0:
        raise ValidationError("Согласованная сумма не изменилась.")
    ObligationEntry.objects.create(
        obligation=obligation,
        amount=delta,
        kind=ObligationEntry.Kind.AMENDMENT,
        source_key=f"amendment:{amendment.pk}",
        effective_date=amendment.effective_date,
        actor=actor,
    )


@transaction.atomic
def record_payment(*, membership, actor, supplier, amount, paid_on, external_reference, method, allocations, key):
    if actor.pk != membership.user_id or not membership.allows("settlements.add_supplierpayment"):
        raise PermissionDenied
    amount = money(amount)
    fingerprint = f"{supplier.pk}:{amount}:{external_reference}"
    existing = existing_operation(
        company=membership.company,
        key=key,
        command=PAYMENT_COMMAND,
        fingerprint=fingerprint,
        already_posted=SupplierPayment.objects.filter(company=membership.company, key=key).exists(),
    )
    if existing is not None:
        return SupplierPayment.objects.get(company=membership.company, key=key)
    if supplier.company_id != membership.company_id:
        raise ValidationError("Поставщик относится к другому предприятию.")
    if sum((item["amount"] for item in allocations), Decimal("0")) > amount:
        raise ValidationError("Зачёт больше суммы оплаты.")
    payment = SupplierPayment.objects.create(
        company=membership.company,
        supplier=supplier,
        amount=amount,
        paid_on=paid_on,
        external_reference=external_reference,
        method=method,
        actor=actor,
        key=key,
    )
    for item in allocations:
        obligation = SupplierObligation.objects.select_for_update().get(pk=item["obligation_id"])
        if obligation.company_id != membership.company_id or obligation.supplier_id != supplier.pk:
            raise ValidationError("Долг относится к другому поставщику.")
        PaymentAllocation.objects.create(payment=payment, obligation=obligation, amount=money(item["amount"]), allocated_on=paid_on)
    finish_operation(
        company=membership.company,
        actor=actor,
        command=PAYMENT_COMMAND,
        key=key,
        fingerprint=fingerprint,
        result_label=external_reference,
        detail=f"Оплата {amount} KGS.",
    )
    return payment


def record_manual_obligation(*, membership, actor, supplier, amount, reference, effective_date):
    if not membership.allows("procurement.view_purchaseprice"):
        raise PermissionDenied
    if supplier.company_id != membership.company_id:
        raise ValidationError("Поставщик относится к другому предприятию.")
    obligation = SupplierObligation.objects.create(
        company=membership.company,
        supplier=supplier,
        manual_reference=reference,
    )
    ObligationEntry.objects.create(
        obligation=obligation,
        amount=money(amount),
        kind=ObligationEntry.Kind.MANUAL,
        source_key=f"manual:{obligation.pk}",
        effective_date=effective_date,
        actor=actor,
    )
    return obligation


def charge_paid_total(charge):
    return charge.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0")


@transaction.atomic
def add_charge_payment(*, charge_id, method, amount, paid_on, reference):
    charge = PurchaseCharge.objects.select_for_update().get(pk=charge_id)
    amount = money(amount)
    if charge_paid_total(charge) + amount > charge.amount:
        raise ValidationError("Оплата расхода больше самого расхода.")
    return charge.payments.create(method=method, amount=amount, paid_on=paid_on, reference=reference)
