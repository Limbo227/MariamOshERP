from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.access import scoped
from apps.procurement.contracts import (
    add_contract_payment,
    add_shipment,
    contract_position,
    create_contract,
    money,
    receive_at_factory,
)
from apps.procurement.forms import (
    ContractForm,
    ContractLineFormSet,
    ContractPayForm,
    ContractShipmentForm,
    FactoryForm,
    PaymentPageForm,
)
from apps.procurement.models import ContractLine, ContractPayment, ContractShipment, SupplyContract


def _text(value):
    return f"{Decimal(value):.2f}"


def _sheet(value, places):
    number = Decimal(value).quantize(Decimal("1") if places == 0 else Decimal("0.01"))
    sign = "−" if number < 0 else ""
    text = f"{abs(number):,.{places}f}".replace(",", " ").replace(".", ",")
    if places:
        text = text.rstrip("0").rstrip(",")
    return sign + (text or "0")


def _price(value):
    return _sheet(value, 2)


def _qty(value):
    number = Decimal(value)
    if number == number.to_integral_value():
        return _sheet(number, 0)
    return _sheet(number, 2)


def _swod_rows(contract):
    lines = list(contract.lines.all())
    payments = list(contract.bank_payments.all())
    slots = []
    for line in lines:
        line_shipments = list(line.shipments.all())
        if line_shipments:
            slots.extend({"shipment": shipment, "line": line} for shipment in line_shipments)
        else:
            slots.append({"shipment": None, "line": line})
    shipments = [slot["shipment"] for slot in slots if slot["shipment"] is not None]
    while len(slots) < len(payments):
        slots.append({"shipment": None, "line": None})
    if not slots:
        slots.append({"shipment": None, "line": None})

    rows = []
    balance = Decimal("0")
    fact_sum = Decimal("0")
    fact_qty = Decimal("0")
    wagons = 0
    same_unit = len({line.product.unit for line in lines}) == 1
    for index, slot in enumerate(slots):
        shipment = slot["shipment"]
        payment = payments[index] if index < len(payments) else None
        fact = shipment.amount if shipment is not None else Decimal("0")
        paid = payment.amount if payment is not None else Decimal("0")
        balance += fact - paid
        if shipment is not None:
            fact_sum += fact
            fact_qty += shipment.quantity
            wagons += shipment.wagon_count
        line = slot["line"]
        rows.append(
            {
                "station": shipment.station.name if shipment is not None else "",
                "product": line.product.name if line is not None and len(lines) > 1 else "",
                "line_id": line.pk if line is not None else None,
                "qty": _qty(line.quantity) if line is not None else "",
                "price": _price(line.price) if line is not None else "",
                "sum": _sheet(line.amount, 2) if line is not None else "",
                "fact_qty": _qty(shipment.quantity) if shipment is not None else "",
                "fact_price": _price(shipment.line.price) if shipment is not None else "",
                "fact_sum": _sheet(fact, 2) if shipment is not None else "",
                "wagons": shipment.wagon_count if shipment is not None else "",
                "paid": _sheet(paid, 2) if payment is not None else "",
                "paid_on": payment.paid_on.strftime("%d.%m.%Y") if payment is not None else "",
                "balance": _sheet(balance, 2),
                "negative": balance < 0,
            }
        )
    _span_stations(rows)
    _span_terms(rows, single_line=len(lines) == 1)
    if rows:
        rows[0]["identity_span"] = len(rows)
        for row in rows[1:]:
            row["identity_span"] = 0
    ordered_qty = sum((line.quantity for line in lines), Decimal("0"))
    ordered_sum = sum((line.amount for line in lines), Decimal("0"))
    paid_sum = sum((payment.amount for payment in payments), Decimal("0"))
    return rows, {
        "qty": _qty(ordered_qty) if same_unit and lines else "",
        "sum": _sheet(ordered_sum, 2),
        "fact_qty": _qty(fact_qty) if same_unit and shipments else "",
        "fact_sum": _sheet(fact_sum, 2),
        "wagons": wagons,
        "paid": _sheet(paid_sum, 2),
        "balance": _sheet(fact_sum - paid_sum, 2),
        "negative": fact_sum - paid_sum < 0,
    }


def _span_stations(rows):
    index = 0
    while index < len(rows):
        name = rows[index]["station"]
        if not name:
            rows[index]["station_span"] = 1
            index += 1
            continue
        end = index + 1
        while end < len(rows) and rows[end]["station"] == name:
            end += 1
        if not any(rows[cursor]["station"] for cursor in range(end, len(rows))):
            while end < len(rows) and rows[end]["line_id"] is None:
                end += 1
        rows[index]["station_span"] = end - index
        for cursor in range(index + 1, end):
            rows[cursor]["station_span"] = 0
        index = end


def _span_terms(rows, *, single_line):
    if single_line and rows:
        rows[0]["terms_span"] = len(rows)
        for row in rows[1:]:
            row["terms_span"] = 0
        return
    index = 0
    while index < len(rows):
        line_id = rows[index]["line_id"]
        if line_id is None:
            rows[index]["terms_span"] = 1
            index += 1
            continue
        end = index + 1
        while end < len(rows) and rows[end]["line_id"] == line_id:
            end += 1
        rows[index]["terms_span"] = end - index
        for cursor in range(index + 1, end):
            rows[cursor]["terms_span"] = 0
        index = end


def _contracts(company):
    shipments = ContractShipment.objects.select_related("station", "factory_arrival", "factory_arrival__warehouse").order_by("pk")
    lines = ContractLine.objects.select_related("product").prefetch_related(Prefetch("shipments", queryset=shipments)).order_by("position", "pk")
    return (
        SupplyContract.objects.filter(company=company)
        .select_related("supplier")
        .prefetch_related(
            Prefetch("lines", queryset=lines),
            Prefetch("bank_payments", queryset=ContractPayment.objects.order_by("paid_on", "pk")),
        )
    )


def _filled_lines(formset):
    return [form.cleaned_data for form in formset if form.cleaned_data.get("product")]


def _cart(formset):
    rows = []
    total = Decimal("0")
    for form in formset:
        quantity = form["quantity"].value()
        price = form["price"].value()
        line_sum = ""
        try:
            if quantity not in (None, "") and price not in (None, ""):
                line_sum = _text(money(Decimal(quantity) * Decimal(price)))
                total += Decimal(line_sum)
        except (ArithmeticError, ValueError):
            line_sum = ""
        rows.append({"form": form, "sum": line_sum})
    return rows, _text(total)


@scoped("core.view_workspace", "procurement.view_supplycontract")
def contract_list(request):
    rows = []
    for contract in _contracts(request.membership.company):
        position = contract_position(contract)
        rows.append({"contract": contract, "position": position, "ordered": _text(position["ordered_sum"]), "due": _text(position["due"])})
    return render(request, "procurement/contract_list.html", {"rows": rows})


@scoped("core.view_workspace", "procurement.add_supplycontract")
def contract_create(request):
    company = request.membership.company
    form = ContractForm(request.POST or None, company=company)
    formset = ContractLineFormSet(request.POST or None, form_kwargs={"company": company})
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            contract = create_contract(
                membership=request.membership,
                actor=request.user,
                supplier=form.cleaned_data["supplier"],
                number=form.cleaned_data["number"],
                lines=_filled_lines(formset),
                key=form.cleaned_data["key"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("contract_detail", pk=contract.pk)
    cart, total = _cart(formset)
    return render(request, "procurement/contract_form.html", {"form": form, "cart": cart, "total": total, "formset": formset})


def _detail(request, contract, shipment_form=None, factory_form=None, payment_form=None):
    contract = _contracts(request.membership.company).get(pk=contract.pk)
    position = contract_position(contract)
    if shipment_form is None and request.membership.allows("procurement.add_contractshipment"):
        shipment_form = ContractShipmentForm(contract=contract)
    if factory_form is None and request.membership.allows("procurement.add_factoryarrival"):
        factory_form = FactoryForm(contract=contract, initial={"arrived_on": timezone.localdate()})
    if payment_form is None and request.membership.allows("procurement.add_contractpayment"):
        payment_form = ContractPayForm(initial={"paid_on": timezone.localdate()})
    return render(
        request,
        "procurement/contract_detail.html",
        {
            "contract": contract,
            "position": position,
            "ordered_text": _text(position["ordered_sum"]),
            "arrived_text": _text(position["arrived_sum"]),
            "paid_text": _text(position["paid"]),
            "due_text": _text(position["due"]),
            "shipment_form": shipment_form,
            "factory_form": factory_form,
            "payment_form": payment_form,
        },
    )


@scoped("core.view_workspace", "procurement.view_supplycontract")
def contract_detail(request, pk):
    contract = get_object_or_404(SupplyContract, pk=pk, company=request.membership.company)
    return _detail(request, contract)


@scoped("core.view_workspace", "procurement.add_contractshipment")
@require_POST
def contract_ship(request, pk):
    contract = get_object_or_404(SupplyContract, pk=pk, company=request.membership.company)
    form = ContractShipmentForm(request.POST, contract=contract)
    if form.is_valid():
        try:
            add_shipment(
                membership=request.membership,
                actor=request.user,
                line=form.cleaned_data["line"],
                station=form.cleaned_data["station"],
                wagon_count=form.cleaned_data["wagon_count"],
                quantity=form.cleaned_data["quantity"],
                key=form.cleaned_data["key"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("contract_detail", pk=pk)
    return _detail(request, contract, shipment_form=form)


@scoped("core.view_workspace", "procurement.add_factoryarrival")
@require_POST
def contract_receive(request, pk):
    contract = get_object_or_404(SupplyContract, pk=pk, company=request.membership.company)
    form = FactoryForm(request.POST, contract=contract)
    if form.is_valid():
        try:
            receive_at_factory(
                membership=request.membership,
                actor=request.user,
                shipment=form.cleaned_data["shipment"],
                warehouse=form.cleaned_data["warehouse"],
                arrived_on=form.cleaned_data["arrived_on"],
                key=form.cleaned_data["key"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("contract_detail", pk=pk)
    return _detail(request, contract, factory_form=form)


@scoped("core.view_workspace", "procurement.add_contractpayment")
@require_POST
def contract_pay(request, pk):
    contract = get_object_or_404(SupplyContract, pk=pk, company=request.membership.company)
    form = ContractPayForm(request.POST)
    if form.is_valid():
        try:
            add_contract_payment(
                membership=request.membership,
                actor=request.user,
                contract=contract,
                paid_on=form.cleaned_data["paid_on"],
                amount=form.cleaned_data["amount"],
                key=form.cleaned_data["key"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("contract_detail", pk=pk)
    return _detail(request, contract, payment_form=form)


@scoped("core.view_workspace", "procurement.view_supplycontract")
def payment_list(request):
    company = request.membership.company
    form = None
    if request.membership.allows("procurement.add_contractpayment"):
        form = PaymentPageForm(request.POST or None, company=company, initial={"paid_on": timezone.localdate()})
        if request.method == "POST" and form.is_valid():
            try:
                add_contract_payment(
                    membership=request.membership,
                    actor=request.user,
                    contract=form.cleaned_data["contract"],
                    paid_on=form.cleaned_data["paid_on"],
                    amount=form.cleaned_data["amount"],
                    key=form.cleaned_data["key"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                return redirect("payment_list")
    rows = []
    for contract in _contracts(company):
        position = contract_position(contract)
        rows.append(
            {
                "contract": contract,
                "ordered": _text(position["ordered_sum"]),
                "arrived": _text(position["arrived_sum"]),
                "paid": _text(position["paid"]),
                "due": _text(position["due"]),
            }
        )
    return render(request, "procurement/payment_list.html", {"rows": rows, "form": form})


@scoped("core.view_workspace", "procurement.view_supplycontract")
def contract_swod(request):
    company = request.membership.company
    grouped = []
    current = None
    for contract in _contracts(company):
        if current is None or current["supplier"].pk != contract.supplier_id:
            current = {"supplier": contract.supplier, "contracts": []}
            grouped.append(current)
        rows, total = _swod_rows(contract)
        current["contracts"].append(
            {
                "number": contract.number,
                "recipient": company.name,
                "rows": rows,
                "total": total,
            }
        )
    return render(request, "procurement/contract_swod.html", {"grouped": grouped})
