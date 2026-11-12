"""Read the wheat workbook and separate Mariam-Osh facts from other companies.

The summary sheet stores quantities in kilograms. Its "tons" heading is the
sheet's own label; 4 wagons of 70,000 kg are recorded as 280,000.
"""

import re
import zipfile
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SIX = Decimal("0.000001")
EXCEL_EPOCH = date(1899, 12, 30)
TOKEN = re.compile(r"\s*(\d+(?:\.\d+)?|[A-Za-z]+\d+|[()+*/-])")
CELL_REF = re.compile(r"^([A-Za-z]+)(\d+)$")
SPEC_NUMBER = re.compile(r"спец\.?\s*(\d+)", re.IGNORECASE)
SPEC_DATE = re.compile(r"от\s+(\d{2})\.(\d{2})\.(\d{4})")
MARIAM = "мариям-ош"


class WorkbookError(Exception):
    pass


class Cell:
    def __init__(self, formula, number, text):
        self.formula = formula
        self.number = number
        self.text = text


class ShipmentFact:
    def __init__(self, row, station, dispatched, accepted, wagons, side_price, when):
        self.row = row
        self.station = station
        self.dispatched = dispatched
        self.accepted = accepted
        self.wagons = wagons
        self.side_price = side_price
        self.when = when


class PaymentFact:
    def __init__(self, row, amount, when, rate):
        self.row = row
        self.amount = amount
        self.when = when
        self.rate = rate
        self.absorbed = False
        self.bank_amount = None
        self.parts = None


class SpecFact:
    def __init__(self, row, number, contract_number, contract_text, when, quantity, price):
        self.row = row
        self.number = number
        self.contract_number = contract_number
        self.contract_text = contract_text
        self.when = when
        self.quantity = quantity
        self.price = price
        self.shipments = []
        self.payments = []


def workbook_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "docs" / "csv" / "СВОД по пшенице -2025.xlsx"


def read_mariam_wheat(path=None):
    path = path or workbook_path()
    sheets = _read_workbook(path)
    summary = sheets["СВОД"]
    book = _first_mariam_contract(summary)
    book.jalalabad_rows = _filled_rows(sheets["Ж-АБАД"])
    book.osh_rows = _filled_rows(sheets["ОШ"])
    _mark_gaps(book)
    return book


def _read_workbook(path):
    with zipfile.ZipFile(path) as package:
        strings = _shared_strings(package)
        names = _sheet_targets(package)
        return {name: _read_sheet(package, target, strings) for name, target in names.items()}


def _shared_strings(package):
    root = ET.fromstring(package.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("m:si", NS):
        values.append("".join(node.text or "" for node in item.iter("{%s}t" % NS["m"])))
    return values


def _sheet_targets(package):
    workbook = ET.fromstring(package.read("xl/workbook.xml"))
    relations = ET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
    targets = {}
    for relation in relations:
        targets[relation.attrib["Id"]] = relation.attrib["Target"]
    names = {}
    relation_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        target = targets[sheet.attrib[relation_key]]
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        names[sheet.attrib["name"]] = target
    return names


def _read_sheet(package, target, strings):
    root = ET.fromstring(package.read(target))
    cells = {}
    for row in root.findall("m:sheetData/m:row", NS):
        for cell in row.findall("m:c", NS):
            ref = cell.attrib["r"]
            formula = cell.find("m:f", NS)
            value = cell.find("m:v", NS)
            kind = cell.attrib.get("t")
            number = None
            text = None
            if kind == "s" and value is not None and value.text:
                text = strings[int(value.text)]
            elif value is not None and value.text and kind not in {"inlineStr", "e", "str"}:
                number = Decimal(value.text).quantize(SIX, rounding=ROUND_HALF_UP)
            cells[(int(re.search(r"\d+", ref).group()), _column(ref))] = Cell(
                None if formula is None else formula.text,
                number,
                text,
            )
    return cells


def _column(ref):
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return index - 1


def _filled_rows(cells):
    return len({row for (row, _column), cell in cells.items() if cell.text or cell.number is not None})


def _first_mariam_contract(cells):
    supplier = ""
    product = "wheat"
    mode = "before"
    current = None
    book = _Book()
    last_row = max(row for row, _column in cells)
    for row in range(1, last_row + 1):
        label = _text(cells, row, 0)
        folded = " ".join(_text(cells, row, column) for column in range(12)).casefold()
        if "отправитель" in label.casefold():
            supplier = label.split(":", 1)[-1].strip()
        if "подсолнух" in folded or "подсолнеч" in folded:
            product = "sunflower"
        elif "пшеница" in folded:
            product = "wheat"
        recipient = _company(_text(cells, row, 2))
        if recipient is None:
            if mode == "posting" and current is not None:
                _add_detail(cells, current, row)
            continue
        if _is_total(recipient):
            current = None
            continue
        mariam = _same_company(recipient, MARIAM)
        if mode == "before" and mariam and product == "wheat":
            mode = "posting"
        elif mode == "posting" and not mariam:
            mode = "after"
            current = None
        if mode == "posting" and mariam and product == "wheat":
            current = _start_spec(cells, book, row, supplier)
        else:
            current = None
            if not mariam:
                book.excluded_companies[recipient] = book.excluded_companies.get(recipient, 0) + 1
            elif product == "sunflower":
                book.sunflower_specs += 1
            else:
                book.later_mariam_specs += 1
    _link_split_payments(book)
    return book


class _Book:
    def __init__(self):
        self.supplier = ""
        self.specs = []
        self.excluded_companies = {}
        self.later_mariam_specs = 0
        self.sunflower_specs = 0
        self.jalalabad_rows = 0
        self.osh_rows = 0
        self.gaps = []


def _start_spec(cells, book, row, supplier):
    contract_text = _text(cells, row, 3)
    match = SPEC_NUMBER.search(contract_text)
    if match is None:
        return None
    dated = SPEC_DATE.search(contract_text)
    if dated is None:
        raise WorkbookError(f"У спецификации в строке {row} нет даты.")
    quantity = _value(cells, row, 4)
    price = _value(cells, row, 5)
    if quantity is None or price is None:
        raise WorkbookError(f"У спецификации в строке {row} нет количества или цены.")
    book.supplier = book.supplier or supplier
    spec = SpecFact(
        row,
        match.group(1),
        contract_text.split(",", 1)[0].strip(),
        contract_text,
        date(int(dated.group(3)), int(dated.group(2)), int(dated.group(1))),
        quantity,
        price,
    )
    book.specs.append(spec)
    _add_detail(cells, spec, row)
    return spec


def _add_detail(cells, spec, row):
    dispatched = _value(cells, row, 7)
    if dispatched is not None and dispatched > 0:
        actual = _value(cells, row, 18)
        accepted = actual if actual is not None and actual > 0 else dispatched
        side = _value(cells, row, 14)
        if _value(cells, row, 17) is None:
            side = None
        wagons = _value(cells, row, 10)
        spec.shipments.append(
            ShipmentFact(
                row,
                _text(cells, row, 0),
                dispatched,
                accepted,
                None if wagons is None else int(wagons),
                side,
                spec.when,
            )
        )
    paid = _value(cells, row, 11)
    if paid is not None and paid > 0:
        paid_on = _value(cells, row, 12)
        if paid_on is None:
            raise WorkbookError(f"У оплаты в строке {row} нет даты.")
        paid_cell = cells.get((row, 11))
        payment = PaymentFact(row, paid, EXCEL_EPOCH + timedelta(days=int(paid_on)), _value(cells, row, 17))
        payment.formula = None if paid_cell is None else paid_cell.formula
        spec.payments.append(payment)


def _link_split_payments(book):
    by_row = {}
    for spec in book.specs:
        for payment in spec.payments:
            by_row[payment.row] = (spec, payment)
    for spec in book.specs:
        for payment in spec.payments:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)-L(\d+)", payment.formula or "", flags=re.IGNORECASE)
            if match is None:
                continue
            other = by_row.get(int(match.group(2)))
            if other is None:
                continue
            bank_amount = Decimal(match.group(1))
            other_spec, other_payment = other
            payment.bank_amount = bank_amount
            payment.parts = [(other_spec, other_payment.amount), (spec, bank_amount - other_payment.amount)]
            other_payment.absorbed = True


def _mark_gaps(book):
    if book.excluded_companies:
        book.gaps.append("other-company")
    if book.jalalabad_rows:
        book.gaps.append("jalalabad-sheet")
    if book.later_mariam_specs:
        book.gaps.append("later-mariam-rows")
    if book.sunflower_specs:
        book.gaps.append("sunflower-section")
    if any(payment.rate is None and not payment.absorbed for spec in book.specs for payment in spec.payments):
        book.gaps.append("payment-without-rate")
    if any(shipment.side_price not in (None, 0) for spec in book.specs for shipment in spec.shipments):
        book.gaps.append("side-costs-not-bank-lines")
    paid_rows = {payment.row for spec in book.specs for payment in spec.payments}
    if any(shipment.row not in paid_rows and not _row_has_payment(spec, shipment) for spec in book.specs for shipment in spec.shipments):
        book.gaps.append("shipment-without-payment")


def _row_has_payment(spec, shipment):
    return any(payment.row == shipment.row for payment in spec.payments)


def _company(value):
    value = (value or "").strip()
    if not value or value.casefold() in {"получатель", "станция"}:
        return None
    return value


def _is_total(value):
    folded = value.casefold().strip(" :")
    return folded.startswith(("итого", "всего", "общий"))


def _same_company(value, expected):
    return value.casefold().replace("ё", "е").replace(" ", "") == expected.replace(" ", "")


def _text(cells, row, column):
    cell = cells.get((row, column))
    return "" if cell is None or cell.text is None else cell.text.strip()


def _value(cells, row, column):
    cell = cells.get((row, column))
    if cell is None:
        return None
    if cell.formula:
        if cell.formula.startswith(("SUM", "sum")) or "!" in cell.formula or "#REF" in cell.formula:
            return cell.number
        try:
            return _evaluate(cells, cell.formula, set())
        except WorkbookError:
            return cell.number
    return cell.number


def _evaluate(cells, formula, stack):
    tokens = TOKEN.findall(formula.replace("$", ""))
    if not tokens:
        raise WorkbookError(formula)
    parser = _Expression(tokens)

    def walk(node):
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "neg":
            return -walk(node[1])
        if kind == "ref":
            row, column = node[1]
            key = (row, column)
            if key in stack:
                raise WorkbookError(formula)
            stack.add(key)
            try:
                return _value(cells, row, column) or Decimal("0")
            finally:
                stack.remove(key)
        left = walk(node[1])
        right = walk(node[2])
        if kind == "+":
            return left + right
        if kind == "-":
            return left - right
        if kind == "*":
            return left * right
        if right == 0:
            raise WorkbookError(formula)
        return left / right

    result = walk(parser.parse())
    if parser.peek() is not None:
        raise WorkbookError(formula)
    return result


class _Expression:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    def peek(self):
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def pop(self):
        token = self.peek()
        self.index += 1
        return token

    def parse(self):
        return self._expr()

    def _expr(self):
        node = self._term()
        while self.peek() in {"+", "-"}:
            operator = self.pop()
            node = (operator, node, self._term())
        return node

    def _term(self):
        node = self._factor()
        while self.peek() in {"*", "/"}:
            operator = self.pop()
            node = (operator, node, self._factor())
        return node

    def _factor(self):
        token = self.peek()
        if token == "-":
            self.pop()
            return ("neg", self._factor())
        if token == "(":
            self.pop()
            node = self._expr()
            if self.pop() != ")":
                raise WorkbookError("Скобка не закрыта.")
            return node
        self.pop()
        ref = CELL_REF.fullmatch(token or "")
        if ref:
            return ("ref", (int(ref.group(2)), _column(ref.group(1))))
        return ("num", Decimal(token))
