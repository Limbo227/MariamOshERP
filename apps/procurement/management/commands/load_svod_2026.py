"""Load Мариям-Ош wheat and bran specifications dated 2026 from the internal свод.

The workbook stays out of git. Payments are taken from the свод in the purchase
currency (rubles). The som column is the operator's own conversion and is not posted.
Bank statement files are not imported: they mix taxes, railway and conversions.
"""

import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Document, Party
from apps.core.services import record_opening, reverse_document
from apps.finance.models import CashOperation, MoneyAccount, MoneyDocument, OpenItem
from apps.finance.queries import item_remaining
from apps.finance.services import record_money
from apps.inventory.models import GoodsReceipt, Product, ProductCategory, UnitOfMeasure, Warehouse
from apps.inventory.products import save_product
from apps.procurement.models import PurchaseContract, PurchaseOrder, RailwayStation, Shipment
from apps.procurement.services import (
    delete_shipment,
    delete_specification,
    post_shipment,
    record_contract,
    record_purchase,
    record_shipment,
    unpost_shipment,
)

MONEY = Decimal("0.01")
QTY = Decimal("0.001")
SPEC_NUMBER = re.compile(r"спец[^\d]{0,3}(\d+)", re.IGNORECASE)
SPEC_DATE = re.compile(r"от\s+(\d{2})\.(\d{2})\.(\d{4})")
CLASS_MARK = re.compile(r"\s*4\s*кл(?:асс)?\.?\s*$", re.IGNORECASE)


def _decimal(value, quantum):
    if value is None or value == "" or isinstance(value, str):
        return None
    if isinstance(value, Decimal):
        number = value
    else:
        number = Decimal(format(value, "f"))
    return number.quantize(quantum, rounding=ROUND_HALF_UP)


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _norm(value):
    text = _text(value).casefold().replace("ё", "е")
    text = CLASS_MARK.sub("", text)
    return " ".join(text.split())


def _is_total(value):
    folded = _text(value).casefold().strip(" :")
    return folded.startswith(("итого", "всего", "общий"))


def _is_mariam(value):
    return _norm(value).replace(" ", "") == "мариям-ош"


def _station_name(value):
    text = CLASS_MARK.sub("", _text(value))
    return " ".join(text.split())


def _end_of_range(value):
    """Last day written in an arrival cell. A single date stays that date."""
    if isinstance(value, datetime):
        return value.date(), ""
    if isinstance(value, date):
        return value, ""
    text = _text(value)
    if not text:
        return None, ""
    found = re.findall(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
    if not found:
        return None, text
    day, month, year = found[-1]
    year = int(year)
    if year < 100:
        year += 2000
    return date(year, int(month), int(day)), text


class Command(BaseCommand):
    help = "Загружает поставки Мариям-Ош из свода, только спецификации с датой от 2026 года."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="",
            help="Путь к xlsx. По умолчанию ищется в docs.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать, что будет загружено. База не меняется.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Сначала снять текущие закупки, их приёмки и оплаты поставщикам.",
        )

    def handle(self, *args, **options):
        path = Path(options["file"]) if options["file"] else _default_workbook()
        if not path.is_file():
            raise CommandError(f"Файл свода не найден: {path}")
        facts = read_svod(path)
        self._report(facts)
        if options["dry_run"]:
            self.stdout.write("Проверка без записи.")
            return
        if not options["replace"]:
            raise CommandError("Добавьте --replace, чтобы снять старые закупки и записать свод 2026.")
        actor = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
        if actor is None:
            raise CommandError("Нет суперпользователя, от чьего имени проводить документы.")
        with transaction.atomic():
            clear_supply(actor)
            load_facts(facts, actor)
        self.stdout.write(self.style.SUCCESS(f"Загружено спецификаций: {len(facts)}."))

    def _report(self, facts):
        for spec in facts:
            shipped = sum((row["quantity"] for row in spec["shipments"]), Decimal("0"))
            paid = sum((row["amount"] for row in spec["payments"]), Decimal("0"))
            guessed = sum(1 for row in spec["shipments"] if row.get("date_from") != "osh")
            self.stdout.write(
                f"{spec['supplier']} / {spec['contract_number']} спец.{spec['number']} "
                f"{spec['when']:%d.%m.%Y} {spec['product']} план {spec['plan']} кг, "
                f"отгружено {shipped} кг, оплата {paid}"
                + (f", без даты прибытия в ОШ: {guessed}" if guessed else "")
            )


def _default_workbook():
    docs = Path(__file__).resolve().parents[4] / "docs"
    matches = sorted(docs.glob("СВОД*.xlsx"))
    if not matches:
        raise CommandError(f"В {docs} нет файла свода.")
    return matches[0]


def read_svod(path):
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True)
    specs = _read_summary(book["СВОД"])
    _attach_osh(specs, _read_osh(book["ОШ"]))
    return specs


def _read_summary(ws):
    section = ""
    sender = ""
    contract_by_sender = {}
    specs = []
    current = None
    station = ""
    for index in range(1, ws.max_row + 1):
        label = _text(ws.cell(index, 1).value)
        party = ws.cell(index, 2).value
        recipient = _text(ws.cell(index, 3).value)
        folded = label.casefold()
        if folded in {"пшеница", "отруби", "подсолнух", "шрот"}:
            section = folded
            current = None
            continue
        if "отправитель" in folded:
            sender = re.sub(r"(?i)^отправитель:\s*", "", label).strip()
            continue
        if _is_total(recipient):
            current = None
            station = ""
            continue
        if party not in (None, "пар-тия", "партия") and _is_mariam(recipient):
            current = None
            station = _station_name(label)
            if section not in {"пшеница", "отруби"}:
                continue
            started = _start_spec(ws, index, sender, section, contract_by_sender)
            if started is None:
                continue
            current = started
            specs.append(current)
            _add_fact(ws, current, index, station, section)
            continue
        if current is None:
            continue
        if label and label.casefold() not in {"станция"}:
            station = _station_name(label)
        _add_fact(ws, current, index, station, section)
    return specs


def _start_spec(ws, index, sender, section, contract_by_sender):
    contract_text = _text(ws.cell(index, 4).value)
    number = SPEC_NUMBER.search(contract_text)
    dated = SPEC_DATE.search(contract_text)
    if number is None or dated is None:
        return None
    when = date(int(dated.group(3)), int(dated.group(2)), int(dated.group(1)))
    if when.year < 2026:
        return None
    plan = _decimal(ws.cell(index, 5).value, QTY)
    price = _decimal(ws.cell(index, 6).value, Decimal("0.0001"))
    if not plan or not price:
        return None
    contract_number = _contract_number(contract_text, sender, contract_by_sender)
    return {
        "supplier": sender,
        "product": "bran" if section == "отруби" else "wheat",
        "contract_number": contract_number,
        "contract_text": contract_text,
        "number": number.group(1),
        "when": when,
        "plan": plan,
        "price": price,
        "shipments": [],
        "payments": [],
    }


def _contract_number(text, sender, memory):
    lead = re.split(r"\s+и\s+спец", text, maxsplit=1, flags=re.IGNORECASE)[0]
    lead = lead.split(",", 1)[0].strip()
    if not lead or lead.casefold().startswith("спец") or SPEC_NUMBER.fullmatch(lead):
        number = memory.get(sender) or lead
    else:
        number = lead
        memory[sender] = number
    if len(number) > 40:
        raise CommandError(f"Номер договора длиннее 40 знаков: {number}")
    return number


def _add_fact(ws, spec, index, station, section):
    if section == "отруби":
        quantity = _decimal(ws.cell(index, 10).value, QTY)
        wagons = ws.cell(index, 13).value
        paid = _decimal(ws.cell(index, 17).value, MONEY)
        paid_on = ws.cell(index, 18).value
    else:
        quantity = _decimal(ws.cell(index, 8).value, QTY)
        wagons = ws.cell(index, 11).value
        paid = _decimal(ws.cell(index, 12).value, MONEY)
        paid_on = ws.cell(index, 13).value
    if quantity and quantity > 0:
        count = int(wagons) if wagons else 1
        spec["shipments"].append(
            {
                "row": index,
                "party": _text(ws.cell(index, 2).value) or spec.get("party") or "",
                "station": station,
                "quantity": quantity,
                "wagons": count,
                "departure": None,
                "arrival": None,
                "arrival_text": "",
                "date_from": "",
            }
        )
        if _text(ws.cell(index, 2).value):
            spec["party"] = _text(ws.cell(index, 2).value)
            spec["shipments"][-1]["party"] = spec["party"]
    if paid and paid > 0:
        when = paid_on.date() if isinstance(paid_on, datetime) else paid_on
        if not isinstance(when, date):
            raise CommandError(f"У оплаты в строке {index} нет даты.")
        spec["payments"].append({"row": index, "amount": paid, "when": when})


def _read_osh(ws):
    rows = []
    party = ""
    station = ""
    for index in range(5, ws.max_row + 1):
        marker = _text(ws.cell(index, 1).value)
        if marker and marker.casefold() not in {"№", "всего:"}:
            if marker != party:
                station = ""
            party = marker
        named = _station_name(ws.cell(index, 3).value)
        if named:
            station = named
        quantity = _decimal(ws.cell(index, 8).value, QTY)
        if not quantity or quantity <= 0:
            continue
        arrival, arrival_text = _end_of_range(ws.cell(index, 5).value)
        departure = ws.cell(index, 4).value
        if isinstance(departure, datetime):
            departure = departure.date()
        wagons = ws.cell(index, 6).value
        spec_no = SPEC_NUMBER.search(_text(ws.cell(index, 10).value))
        rows.append(
            {
                "party": party,
                "spec": spec_no.group(1) if spec_no else "",
                "station": station,
                "quantity": quantity,
                "wagons": int(wagons) if isinstance(wagons, (int, float, Decimal)) else None,
                "departure": departure if isinstance(departure, date) else None,
                "arrival": arrival,
                "arrival_text": arrival_text,
                "used": False,
            }
        )
    return rows


def _attach_osh(specs, arrivals):
    for spec in specs:
        for shipment in spec["shipments"]:
            match = _take_arrival(arrivals, spec, shipment)
            if match is not None:
                shipment["departure"] = match["departure"]
                shipment["arrival"] = match["arrival"]
                shipment["arrival_text"] = match["arrival_text"]
                if match["station"]:
                    shipment["station"] = match["station"]
            if shipment["arrival"] is not None:
                shipment["date_from"] = "osh"
            elif shipment["departure"] is not None:
                shipment["arrival"] = shipment["departure"]
                shipment["date_from"] = "departure"
            else:
                fallback = spec["payments"][0]["when"] if spec["payments"] else spec["when"]
                shipment["arrival"] = fallback
                shipment["date_from"] = "payment"


def _take_arrival(arrivals, spec, shipment):
    party = spec.get("party") or ""
    pool = [row for row in arrivals if not row["used"]]
    candidates = [row for row in pool if row["party"] == party] or [
        row for row in pool if row["spec"] == spec["number"] and row["quantity"] == shipment["quantity"]
    ]
    station = _norm(shipment["station"])
    exact = [
        row
        for row in candidates
        if row["quantity"] == shipment["quantity"]
        and _norm(row["station"]) == station
        and (row["wagons"] in (None, shipment["wagons"]))
    ]
    if not exact:
        exact = [
            row
            for row in candidates
            if row["quantity"] == shipment["quantity"] and (not station or _norm(row["station"]) in {"", station})
        ]
    if not exact:
        exact = [row for row in candidates if row["quantity"] == shipment["quantity"]]
    if not exact:
        return None
    chosen = exact[0]
    chosen["used"] = True
    return chosen


def _erase_documents(*documents):
    """Delete posted documents the domain API refuses to remove, after their ledger rows are gone."""
    from apps.finance.models import Allocation, MoneyMove, OpenItem
    from apps.inventory.models import StockMove

    ids = [document.pk for document in documents if document is not None]
    allocations = Allocation.objects.filter(
        Q(document_id__in=ids) | Q(we_owe__document_id__in=ids) | Q(they_owe__document_id__in=ids)
    )
    Allocation.objects.filter(reversal_of__in=allocations).delete()
    allocations.delete()
    OpenItem.objects.filter(document_id__in=ids).delete()
    MoneyMove.objects.filter(document_id__in=ids).delete()
    StockMove.objects.filter(document_id__in=ids).delete()
    for document in documents:
        if document is not None:
            Document.objects.filter(pk=document.pk).delete()


def _drop_reversed_receipt(receipt):
    """Remove a receipt that was already reversed, so its purchase can be deleted."""
    document = receipt.document
    reversal = Document.objects.filter(reverses=document).first()
    receipt.lines.all().delete()
    GoodsReceipt.objects.filter(pk=receipt.pk).delete()
    _erase_documents(reversal, document)


def _drop_money(money):
    document = money.document
    reversal = Document.objects.filter(reverses=document).first()
    MoneyDocument.objects.filter(pk=money.pk).delete()
    _erase_documents(reversal, document)


def clear_supply(actor):
    """Remove purchase documents so the свод is the only supply history."""
    from apps.core.posting import delete_draft_document, unpost_document

    today = timezone.localdate()
    for shipment in Shipment.objects.filter(status=Shipment.Status.POSTED).order_by("-pk"):
        unpost_shipment(shipment, actor=actor)
    for issue in list(
        Document.objects.filter(
            kind=Document.Kind.ISSUE, state=Document.State.POSTED, reversal__isnull=True
        ).order_by("-effective_date", "-pk")
    ):
        unpost_document(issue, actor=actor, detail="Выдача снята перед заменой закупок сводом 2026.")
        delete_draft_document(issue, actor=actor)
    manuals = GoodsReceipt.objects.filter(
        document__state=Document.State.POSTED, source_shipment__isnull=True
    ).select_related("document")
    for receipt in list(manuals):
        if Document.objects.filter(reverses=receipt.document).exists():
            _drop_reversed_receipt(receipt)
            continue
        unpost_document(receipt.document, actor=actor, detail="Снято перед загрузкой свода 2026.")
        delete_draft_document(receipt.document, actor=actor)
    expenses = MoneyDocument.objects.filter(Q(shipment__isnull=False) | Q(order__isnull=False)).select_related(
        "document"
    )
    for money in list(expenses.order_by("-pk")):
        document = money.document
        if Document.objects.filter(reverses=document).exists():
            _drop_money(money)
            continue
        if document.state == Document.State.POSTED:
            unpost_document(document, actor=actor, detail="Расход закупки снят перед загрузкой свода 2026.")
        document.refresh_from_db()
        if document.state == Document.State.DRAFT:
            delete_draft_document(document, actor=actor)
    for shipment in list(Shipment.objects.all()):
        delete_shipment(shipment, actor=actor)
    for order in list(PurchaseOrder.objects.all()):
        delete_specification(order, actor=actor)
    for document in list(
        Document.objects.filter(kind=Document.Kind.SETTLEMENT, state=Document.State.POSTED, reversal__isnull=True)
    ):
        reverse_document(document, effective_date=today, note="Снято перед загрузкой свода 2026.", actor=actor)
    pay = CashOperation.objects.get(code="pay-supplier")
    payments = MoneyDocument.objects.filter(
        operation=pay, document__state=Document.State.POSTED, document__reversal__isnull=True
    )
    for money in list(payments):
        reverse_document(money.document, effective_date=today, note="Снято перед загрузкой свода 2026.", actor=actor)
    PurchaseContract.objects.filter(specifications__isnull=True).delete()


def load_facts(facts, actor):
    grain = ProductCategory.objects.get(code="GRAIN")
    kilogram = UnitOfMeasure.objects.get(code="KG")
    wheat = _product("PUR-WHEAT", "Пшеница", grain, kilogram)
    bran = _product("PUR-BRAN", "Отруби", grain, kilogram)
    elevator = Warehouse.objects.get(code="RAW-1")
    rub = MoneyAccount.objects.filter(currency="RUB", kind=MoneyAccount.Kind.BANK, active=True).first()
    if rub is None:
        rub = MoneyAccount.objects.create(name="МБанк RUB", kind=MoneyAccount.Kind.BANK, currency="RUB")
    for code, name in (("KGS", "МБанк KGS"), ("KZT", "МБанк KZT"), ("USD", "МБанк USD")):
        if not MoneyAccount.objects.filter(currency=code, kind=MoneyAccount.Kind.BANK, active=True).exists():
            MoneyAccount.objects.create(name=name, kind=MoneyAccount.Kind.BANK, currency=code)
    destination = _station("Ош")
    pay = CashOperation.objects.get(code="pay-supplier")
    orders = []
    contracts = {}
    for spec in facts:
        supplier = _supplier(spec["supplier"])
        key = (supplier.pk, spec["contract_number"])
        contract = contracts.get(key)
        if contract is None:
            contract = record_contract(
                supplier=supplier,
                number=spec["contract_number"],
                contract_date=spec["when"],
                currency="RUB",
                description=spec["contract_text"],
            )
            contracts[key] = contract
        product = bran if spec["product"] == "bran" else wheat
        order = record_purchase(
            supplier=supplier,
            effective_date=spec["when"],
            lines=[{"product": product, "quantity": spec["plan"], "price": spec["price"]}],
            note=spec["contract_text"],
            actor=actor,
            contract=contract,
            specification_number=spec["number"],
            currency="RUB",
        )
        orders.append((spec, order))
    posted = []
    for spec, order in orders:
        for shipment in spec["shipments"]:
            origin = _station(shipment["station"] or "Не указана")
            note = f"Свод, строка {shipment['row']}."
            if shipment["date_from"] == "departure":
                note += " Даты прибытия в листе ОШ нет, приёмка проведена датой отправки."
            elif shipment["date_from"] == "payment":
                note += " В листе ОШ нет дат этой поставки. Приёмка проведена датой первой оплаты спецификации."
            elif shipment["arrival_text"]:
                note += f" В листе ОШ прибытие: {shipment['arrival_text']}."
            row = record_shipment(
                order=order,
                quantity=shipment["quantity"],
                departure_date=shipment["departure"],
                arrival_date=shipment["arrival"],
                notes=note,
                departure_station=origin,
                destination_station=destination,
                wagon_count=shipment["wagons"],
                actor=actor,
            )
            posted.append((shipment["arrival"], shipment["row"], row))
    for _when, _row, shipment in sorted(posted, key=lambda item: (item[0], item[1])):
        post_shipment(shipment, warehouse=elevator, actor=actor)
    paid_total = sum((row["amount"] for spec, _order in orders for row in spec["payments"]), Decimal("0"))
    if paid_total:
        first = min(row["when"] for spec, _order in orders for row in spec["payments"])
        record_opening(
            effective_date=first - timedelta(days=1),
            money=[{"account": rub, "amount": paid_total}],
            note="Остаток рублёвого счёта, чтобы провести оплаты свода 2026.",
            actor=actor,
        )
    events = []
    for spec, order in orders:
        for payment in spec["payments"]:
            events.append((payment["when"], payment["row"], order, payment))
    for when, row_number, order, payment in sorted(events, key=lambda item: (item[0], item[1])):
        open_amount = _open_debt(order)
        take = min(payment["amount"], open_amount)
        kwargs = {"fifo": False}
        if take > 0:
            kwargs = {"allocations": [{"order": order, "amount": take}]}
        record_money(
            operation=pay,
            account=rub,
            amount=payment["amount"],
            effective_date=when,
            party=order.supplier,
            external_reference=f"SVOD-{row_number}",
            note=f"Оплата по своду, строка {row_number}, спецификация {order.specification_number}.",
            actor=actor,
            **kwargs,
        )


def _product(sku, name, category, unit):
    product = Product.objects.filter(sku=sku).first()
    if product is None:
        product = save_product(sku=sku, name=name, category=category, unit=unit, unit_weight_kg=Decimal("1"))
    product.kind = Product.Kind.GRAIN
    product.category = category
    product.unit = unit.code
    product.save()
    return product


def _supplier(name):
    party = Party.objects.filter(name__iexact=name, is_supplier=True).first()
    if party is None:
        party = Party.objects.create(name=name, is_supplier=True)
    return party


def _station(name):
    cleaned = _station_name(name) or "Не указана"
    station = RailwayStation.objects.filter(name__iexact=cleaned).first()
    if station is None:
        station = RailwayStation.objects.create(name=cleaned)
    return station


def _open_debt(order):
    total = Decimal("0")
    items = OpenItem.objects.filter(
        order=order,
        side=OpenItem.Side.WE_OWE,
        lane=OpenItem.Lane.PAYABLE,
        document__state=Document.State.POSTED,
        document__reversal__isnull=True,
    )
    for item in items:
        total += item_remaining(item)
    return total
