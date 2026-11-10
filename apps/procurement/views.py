from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.access import scoped, warehouses_for
from apps.inventory.models import GoodsReceipt, ReceiptLine, StorageLocation
from apps.inventory.posting import create_receipt, post_receipt
from apps.procurement.forms import (
    AmendmentForm,
    ChargeForm,
    CustomsAcceptForm,
    OrderHeaderForm,
    OrderLineFormSet,
    PassportForm,
    PaymentForm,
    ShipmentForm,
    ShipmentStateForm,
    StorageReceiveForm,
    WagonForm,
)
from apps.procurement.models import CustomsAcceptance, PurchaseCharge, PurchaseOrder, Shipment
from apps.procurement.services import (
    OrderLineInput,
    accept_at_customs,
    add_wagon,
    amend_order,
    confirm_order,
    create_order,
    create_shipment,
)
from apps.quality.models import SupplierQualityValue
from apps.quality.services import compare_quality
from apps.settlements.models import SupplierObligation
from apps.settlements.services import (
    add_charge_payment,
    agreed_total,
    money,
    obligation_position,
    record_payment,
)


def _order(membership, pk):
    return get_object_or_404(PurchaseOrder.objects.filter(company=membership.company).select_related("supplier"), pk=pk)


@scoped("core.view_workspace", "procurement.view_purchaseorder")
def order_list(request):
    zero = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=3))
    customs_qty = CustomsAcceptance.objects.filter(order=OuterRef("pk")).values("order").annotate(total=Sum("quantity")).values("total")
    stored_qty = ReceiptLine.objects.filter(document__order=OuterRef("pk"), document__state=GoodsReceipt.State.POSTED).values("document__order").annotate(total=Sum("quantity")).values("total")
    documents = (
        PurchaseOrder.objects.filter(company=request.membership.company)
        .select_related("supplier")
        .annotate(customs_qty=Coalesce(Subquery(customs_qty), zero), stored_qty=Coalesce(Subquery(stored_qty), zero))
        .prefetch_related("lines__product")
    )
    return render(request, "procurement/order_list.html", {"page": Paginator(documents, 50).get_page(request.GET.get("page"))})


@scoped("core.view_workspace", "procurement.add_purchaseorder")
def order_create(request):
    membership = request.membership
    header = OrderHeaderForm(request.POST or None, company=membership.company, initial={"effective_date": timezone.localdate()})
    formset = OrderLineFormSet(request.POST or None, prefix="lines", form_kwargs={"company": membership.company})
    if request.method == "POST" and header.is_valid() and formset.is_valid():
        lines = [
            OrderLineInput(product_id=row["product"].pk, quantity=row["quantity"], unit_price=row["unit_price"])
            for row in formset.cleaned_data
            if row
        ]
        try:
            order = create_order(
                membership=membership,
                actor=request.user,
                supplier=header.cleaned_data["supplier"],
                reference=header.cleaned_data["reference"],
                contract_reference=header.cleaned_data["contract_reference"],
                batch_number=header.cleaned_data["batch_number"],
                wagon_count=header.cleaned_data["wagon_count"],
                effective_date=header.cleaned_data["effective_date"],
                lines=lines,
                key=header.cleaned_data["key"],
            )
        except ValidationError as exc:
            header.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("order_detail", pk=order.pk)
    return render(request, "procurement/order_form.html", {"header": header, "formset": formset})


@scoped("core.view_workspace", "procurement.view_purchaseorder")
def order_detail(request, pk):
    membership = request.membership
    order = _order(membership, pk)
    lines = list(order.lines.select_related("product"))
    show_prices = membership.allows("procurement.view_purchaseprice")
    if show_prices:
        for line in lines:
            line.display_amount = None if line.unit_price is None else money(line.quantity * line.unit_price)
            line.price_text = "" if line.unit_price is None else f"{line.unit_price:.2f}"
            line.amount_text = "" if line.display_amount is None else f"{line.display_amount:.2f}"
    position = None
    if show_prices and order.state == PurchaseOrder.State.CONFIRMED:
        position = obligation_position(order.supplierobligation)
    amendment = AmendmentForm(lines=lines, initial={"effective_date": timezone.localdate()}) if show_prices and order.state == PurchaseOrder.State.CONFIRMED else None
    payment = PaymentForm(initial={"paid_on": timezone.localdate()}) if show_prices and order.state == PurchaseOrder.State.CONFIRMED else None
    acceptances = order.acceptances.all()
    receipts = list(order.receipts.filter(state=GoodsReceipt.State.POSTED).prefetch_related("lines"))
    for receipt in receipts:
        receipt.posted_quantity = sum((item.quantity for item in receipt.lines.all()), Decimal("0"))
    locations = StorageLocation.objects.filter(warehouse__in=warehouses_for(membership), warehouse__kind="RAW", active=True)
    can_accept = membership.allows("procurement.add_customsacceptance") and order.state == PurchaseOrder.State.CONFIRMED
    can_store = membership.allows("inventory.add_goodsreceipt") and acceptances.exists() and locations.exists()
    return render(
        request,
        "procurement/order_detail.html",
        {
            "order": order,
            "lines": lines,
            "show_prices": show_prices,
            "position": position,
            "agreed_text": f"{agreed_total(order):.2f}" if show_prices and order.state == PurchaseOrder.State.CONFIRMED else "",
            "due_text": f"{position['due']:.2f}" if position else "",
            "credit_text": f"{position['credit']:.2f}" if position else "",
            "amendment": amendment,
            "payment": payment,
            "acceptances": acceptances,
            "receipts": receipts,
            "customs_form": CustomsAcceptForm(initial={"accepted_on": timezone.localdate()}) if can_accept else None,
            "storage_form": StorageReceiveForm(acceptances=acceptances, lines=order.lines.all(), locations=locations) if can_store else None,
        },
    )


@scoped("core.view_workspace", "procurement.confirm_purchaseorder")
@require_POST
def order_confirm(request, pk):
    try:
        confirm_order(membership=request.membership, actor=request.user, order_id=pk)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("order_detail", pk=pk)


@scoped("core.view_workspace", "procurement.add_customsacceptance")
@require_POST
def order_accept(request, pk):
    form = CustomsAcceptForm(request.POST)
    if form.is_valid():
        try:
            accept_at_customs(
                membership=request.membership,
                actor=request.user,
                order_id=pk,
                port=form.cleaned_data["port"],
                quantity=form.cleaned_data["quantity"],
                accepted_on=form.cleaned_data["accepted_on"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "Проверьте отметку таможни.")
    return redirect("order_detail", pk=pk)


@scoped("core.view_workspace", "inventory.add_goodsreceipt")
@require_POST
def order_receive(request, pk):
    membership = request.membership
    order = _order(membership, pk)
    locations = StorageLocation.objects.filter(warehouse__in=warehouses_for(membership), warehouse__kind="RAW", active=True)
    form = StorageReceiveForm(request.POST, acceptances=order.acceptances.all(), lines=order.lines.all(), locations=locations)
    if not form.is_valid():
        messages.error(request, "Проверьте приход.")
        return redirect("order_detail", pk=pk)
    line = form.cleaned_data["line"] or order.lines.get()
    acceptance = form.cleaned_data["acceptance"] or order.acceptances.get()
    location = form.cleaned_data["location"]
    if not locations.filter(pk=location.pk).exists():
        raise PermissionDenied
    try:
        receipt = create_receipt(
            membership=membership,
            actor=request.user,
            supplier=order.supplier,
            warehouse=location.warehouse,
            reference=f"Приход: {order.reference}",
            effective_date=timezone.localdate(),
            lines=[{
                "product_id": line.product_id,
                "location_id": location.pk,
                "order_line_id": line.pk,
                "quantity": form.cleaned_data["quantity"],
                "basis": form.cleaned_data["basis"],
                "batch_reference": order.batch_number,
            }],
            order_id=order.pk,
            customs_acceptance_id=acceptance.pk,
            key=uuid4(),
        )
        post_receipt(membership=membership, actor=request.user, receipt_id=receipt.pk)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("order_detail", pk=pk)


@scoped("core.view_workspace", "procurement.amend_purchaseorder")
@require_POST
def order_amend(request, pk):
    order = _order(request.membership, pk)
    form = AmendmentForm(request.POST, lines=order.lines.select_related("product"))
    if form.is_valid():
        try:
            amend_order(
                membership=request.membership,
                actor=request.user,
                order_id=order.pk,
                reason=form.cleaned_data["reason"],
                effective_date=form.cleaned_data["effective_date"],
                terms=form.terms(),
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        messages.error(request, "Проверьте новые условия.")
    return redirect("order_detail", pk=pk)


@scoped("core.view_workspace", "settlements.add_supplierpayment")
@require_POST
def order_pay(request, pk):
    order = _order(request.membership, pk)
    form = PaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Проверьте оплату.")
        return redirect("order_detail", pk=pk)
    obligation = SupplierObligation.objects.get(order=order)
    try:
        record_payment(
            membership=request.membership,
            actor=request.user,
            supplier=order.supplier,
            amount=form.cleaned_data["amount"],
            paid_on=form.cleaned_data["paid_on"],
            external_reference=form.cleaned_data["external_reference"],
            method=form.cleaned_data["method"],
            allocations=[{"obligation_id": obligation.pk, "amount": form.cleaned_data["amount"]}],
            key=form.cleaned_data["key"],
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("order_detail", pk=pk)


@scoped("core.view_workspace", "procurement.view_shipment")
def shipment_list(request):
    documents = Shipment.objects.filter(company=request.membership.company).select_related("supplier")
    return render(request, "procurement/shipment_list.html", {"page": Paginator(documents, 50).get_page(request.GET.get("page"))})


@scoped("core.view_workspace", "procurement.add_shipment")
def shipment_create(request):
    form = ShipmentForm(request.POST or None, company=request.membership.company, initial={"expected_date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        try:
            shipment = create_shipment(
                membership=request.membership,
                actor=request.user,
                supplier=form.cleaned_data["supplier"],
                reference=form.cleaned_data["reference"],
                customs_port=form.cleaned_data["customs_port"],
                order_id=form.cleaned_data["order"].pk if form.cleaned_data["order"] else None,
                expected_date=form.cleaned_data["expected_date"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("shipment_detail", pk=shipment.pk)
    return render(request, "procurement/shipment_form.html", {"form": form})


@scoped("core.view_workspace", "procurement.view_shipment")
def shipment_detail(request, pk):
    shipment = get_object_or_404(Shipment.objects.filter(company=request.membership.company).select_related("supplier", "order"), pk=pk)
    units = list(shipment.units.all())
    comparisons = []
    for unit in units:
        comparisons.append({"unit": unit, "rows": compare_quality(shipment=shipment, transport_unit=unit)})
    return render(
        request,
        "procurement/shipment_detail.html",
        {
            "shipment": shipment,
            "units": units,
            "charges": shipment.charges.prefetch_related("payments"),
            "passport": shipment.passport_values.all(),
            "comparisons": comparisons,
            "wagon_form": WagonForm(),
            "charge_form": ChargeForm(initial={"charged_on": timezone.localdate()}),
            "passport_form": PassportForm(),
            "state_form": ShipmentStateForm(initial={"state": shipment.state}),
            "can_edit": request.membership.allows("procurement.change_shipment"),
            "can_charge": request.membership.allows("procurement.add_purchasecharge"),
            "can_passport": request.membership.allows("quality.add_supplierqualityvalue"),
        },
    )


@scoped("core.view_workspace", "procurement.add_transportunit")
@require_POST
def shipment_wagon(request, pk):
    form = WagonForm(request.POST)
    if form.is_valid():
        try:
            add_wagon(
                membership=request.membership,
                shipment_id=pk,
                identifier=form.cleaned_data["identifier"],
                declared_quantity=form.cleaned_data["declared_quantity"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("shipment_detail", pk=pk)


@scoped("core.view_workspace", "procurement.add_purchasecharge")
@require_POST
def shipment_charge(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk, company=request.membership.company)
    form = ChargeForm(request.POST)
    if form.is_valid():
        charge = PurchaseCharge.objects.create(
            shipment=shipment,
            counterparty=form.cleaned_data["counterparty"],
            amount=money(form.cleaned_data["amount"]),
            charged_on=form.cleaned_data["charged_on"],
            note=form.cleaned_data["note"],
        )
        try:
            add_charge_payment(charge_id=charge.pk, method=form.cleaned_data["method"], amount=charge.amount, paid_on=charge.charged_on, reference=shipment.reference)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("shipment_detail", pk=pk)


@scoped("core.view_workspace", "quality.add_supplierqualityvalue")
@require_POST
def shipment_passport(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk, company=request.membership.company)
    form = PassportForm(request.POST)
    if form.is_valid():
        SupplierQualityValue.objects.create(
            shipment=shipment,
            parameter=form.cleaned_data["parameter"],
            number=form.cleaned_data["number"],
            unit=form.cleaned_data["unit"],
            passport_version=form.cleaned_data["passport_version"],
        )
    return redirect("shipment_detail", pk=pk)


@scoped("core.view_workspace", "procurement.change_shipment")
@require_POST
def shipment_state(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk, company=request.membership.company)
    form = ShipmentStateForm(request.POST)
    if form.is_valid():
        shipment.state = form.cleaned_data["state"]
        shipment.save(update_fields=["state"])
    return redirect("shipment_detail", pk=pk)
