"""Demo history for the workplace. Safe to run again: it stops if KZ-2025/04 already exists.

Does not change documents that were already in the database, except one receipt
against the open sack order PUR-000004 and one draft shipment on specification 1
of KZ-2026/15. Both go through the normal posting services.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Party
from apps.core.services import record_opening, reverse_document
from apps.finance.models import CashOperation, ExpenseCategory, MoneyAccount
from apps.finance.services import (
    recognize_accountable,
    record_money,
    record_shipment_expense,
    settle_supplier,
)
from apps.inventory.models import Product, ProductCategory, Warehouse
from apps.inventory.products import save_product
from apps.inventory.services import record_issue, record_receipt
from apps.procurement.models import DeliveryTerm, PurchaseContract, PurchaseOrder, RailwayStation
from apps.procurement.services import (
    declare_wagons,
    post_shipment,
    record_contract,
    record_purchase,
    record_shipment,
)
from apps.sales.services import record_sale

D = Decimal


class Command(BaseCommand):
    help = "Добавляет демонстрационную историю: договоры, поставки, заказы, оплаты и склад за 2025–2026."

    def handle(self, *args, **options):
        if PurchaseContract.objects.filter(number="KZ-2025/04").exists():
            self.stdout.write("Демо-данные уже есть (договор KZ-2025/04). Повторно не добавляю.")
            return
        with transaction.atomic():
            self._load()
        self.stdout.write(self.style.SUCCESS("Демо-данные добавлены."))

    def _load(self):
        user = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
        grain = ProductCategory.objects.get(code="GRAIN")
        pack = ProductCategory.objects.get(code="PACK")
        finished = ProductCategory.objects.get(code="FG")
        materials = ProductCategory.objects.create(
            code="MAT",
            name="Сырьё и материалы",
            description="Премиксы, масло и прочее сырьё, которое не зерно.",
            active=True,
        )
        elevator = Warehouse.objects.get(code="RAW-1")
        flour_wh = Warehouse.objects.get(code="FG-1")
        pack_wh = Warehouse.objects.get(code="PACK-1")
        Warehouse.objects.create(
            code="MAT-1",
            name="Склад материалов",
            kind=Warehouse.Kind.RAW,
            category=materials,
            active=True,
        )
        mat_wh = Warehouse.objects.get(code="MAT-1")

        wheat4 = Product.objects.get(sku="WHEAT-4")
        flour_bars = Product.objects.get(sku="FLOUR-BARS-1-50")
        flour_hs = Product.objects.get(sku="FLOUR-HS-50")
        sack50 = Product.objects.get(sku="SACK-50")
        wheat3 = self._product("WHEAT-3", "Пшеница 3 класс", Product.Kind.GRAIN, grain, "KG", D("1"))
        premix = self._product("PREMIX", "Премикс хлебопекарный", Product.Kind.RAW, materials, "KG", D("1"))
        oil = self._product("OIL-SUN", "Масло подсолнечное", Product.Kind.RAW, materials, "L", None)
        sack25 = self._product("SACK-25", "Мешок полипропилен 25 кг", Product.Kind.PACKAGING, pack, "PCS", None)
        flour25 = self._product("FLOUR-1-25", "Мука 1 сорт 25 кг", Product.Kind.FINISHED, finished, "BAG", D("25"))
        bran = self._product("BRAN", "Отруби пшеничные", Product.Kind.FINISHED, finished, "KG", D("1"))

        kaz = Party.objects.get(name="ТОО Каззерно Экспорт")
        sibagro = Party.objects.get(name="ООО Сибагро")
        astyk = Party.objects.create(
            name="ТОО «Астык Кокшетау»",
            is_supplier=True,
            note="Пшеница 3 и 4 класса. Станции Петропавловск, Караганда, Астана.",
        )
        rakhimov = Party.objects.create(
            name="ИП Рахимов А.К.",
            is_supplier=True,
            note="Премиксы и масло. Ош, склад на ул. Ленина.",
        )
        dan = Party.objects.create(
            name="ОсОО «Дан-Азык»",
            is_supplier=True,
            note="Мука и отруби, когда свой помол не закрывает заказ.",
        )
        nurlan = Party.objects.create(name="ОсОО «Нурлан-Нан»", is_customer=True, note="Пекарня, Ош. Отгрузка мешками.")
        altyn = Party.objects.create(name="ОсОО «Алтын Дан»", is_customer=True, note="Опт, Бишкек. Берёт высший сорт.")
        bakyt = Party.objects.create(name="Бакыт Асан уулу", is_employee=True, note="Кладовщик элеватора.")
        aigul = Party.objects.get(name="Пекарня Айгуль")

        manas = self._station("Манас", "716507", "Кыргызстан")
        petropavlovsk = self._station("Петропавловск", "684001", "Казахстан")
        karaganda = self._station("Караганда-Сортировочная", "690200", "Казахстан")
        astana = self._station("Астана-1", "690002", "Казахстан")
        kok = RailwayStation.objects.get(name="Кокшетау-1")
        dap = DeliveryTerm.objects.get(code="DAP")
        fca = DeliveryTerm.objects.get(code="FCA")

        usd = MoneyAccount.objects.get(name="Айыл Банк USD")
        kgs_bank = MoneyAccount.objects.get(name="Оптима KGS")
        cash = MoneyAccount.objects.get(name="Касса офис")
        kzt = MoneyAccount.objects.create(name="Оптима KZT", kind=MoneyAccount.Kind.BANK, currency="KZT")
        pay = CashOperation.objects.get(code="pay-supplier")
        receive = CashOperation.objects.get(code="receive-customer")
        advance = CashOperation.objects.get(code="accountable-advance")
        give_back = CashOperation.objects.get(code="accountable-return")
        unloading = CashOperation.objects.get(code="unloading")
        electricity = CashOperation.objects.get(code="electricity")
        tax = CashOperation.objects.get(code="tax")
        deposit = CashOperation.objects.get(code="deposit-to-bank")
        rail = ExpenseCategory.objects.get(code="RAIL")
        customs = ExpenseCategory.objects.get(code="CUSTOMS")

        record_opening(
            effective_date=date(2025, 3, 1),
            money=[
                {"account": usd, "amount": D("500000.00")},
                {"account": kgs_bank, "amount": D("15000000.00")},
                {"account": cash, "amount": D("400000.00")},
                {"account": kzt, "amount": D("100000000.00")},
            ],
            note="Деньги на счетах перед сезоном 2025",
            actor=user,
        )

        old = record_contract(
            supplier=kaz,
            number="KZ-2025/04",
            contract_date=date(2025, 4, 2),
            currency="USD",
            delivery_term=dap,
            end_date=date(2026, 3, 31),
            volume_tons=D("1800"),
            amount_limit=D("420000"),
            prepayment_percent=D("20"),
            payment_terms="Предоплата 20%, остаток 5 банковских дней после приёмки",
            description="Пшеница 4 класс, урожай 2024. Приёмка на станции Манас.",
        )
        spec_old_1 = self._spec(
            kaz, old, "1", date(2025, 4, 8), wheat4, "1200000", "0.2100", "USD", dap, "Спецификация на 1 200 т."
        )
        spec_old_2 = self._spec(
            kaz, old, "2", date(2025, 8, 1), wheat4, "600000", "0.1980", "USD", dap, "Вторая спецификация, цена ниже."
        )
        self._pay(pay, kaz, usd, "40000", date(2025, 4, 10), "Предоплата 20% по KZ-2025/04", "SWIFT-2025-0410", user)

        may = self._ship(
            spec_old_1, kok, manas, date(2025, 5, 6), date(2025, 5, 18),
            [("95051001", "68400"), ("95051002", "67600")],
            "Майская отгрузка, 2 вагона", elevator, user,
        )
        july = self._ship(
            spec_old_1, kok, manas, date(2025, 7, 2), date(2025, 7, 14),
            [("95051011", "69200"), ("95051012", "70100"), ("95051013", "68700")],
            "Июль, 3 вагона", elevator, user,
        )
        self._ship(
            spec_old_2, kok, manas, date(2025, 8, 20), date(2025, 9, 2),
            [("95052001", "68200"), ("95052002", "69100"), ("95052003", "67700")],
            "Спецификация 2, первая партия", elevator, user,
        )
        self._ship(
            spec_old_1, kok, manas, date(2025, 9, 9), date(2025, 9, 21),
            [("95051021", "70500"), ("95051022", "69500")],
            "Сентябрь, 2 вагона", elevator, user,
        )
        self._ship(
            spec_old_2, kok, manas, date(2025, 10, 15), date(2025, 10, 28),
            [("95052011", "67400"), ("95052012", "70600")],
            "Спецификация 2, вторая партия", elevator, user,
        )
        november = self._ship(
            spec_old_1, kok, manas, date(2025, 11, 11), date(2025, 11, 25),
            [("95051031", "68000"), ("95051032", "68000"), ("95051033", "68000"), ("95051034", "68000")],
            "Ноябрь, 4 вагона", elevator, user,
        )
        self._ship(
            spec_old_1, kok, manas, date(2026, 1, 14), date(2026, 1, 27),
            [("95051041", "71000"), ("95051042", "69000")],
            "Январь 2026, закрытие сезона", elevator, user,
        )
        self._ship(
            spec_old_2, kok, manas, date(2026, 2, 2), date(2026, 2, 18),
            [("95052021", "66000"), ("95052022", "66000")],
            "Черновик: вагоны сверены, приёмку ещё не проводили", elevator, user, post=False,
        )

        record_shipment_expense(
            account=kgs_bank, amount=D("186400"), effective_date=date(2025, 5, 20),
            category=rail, shipment=may, note="ЖД тариф, 2 вагона, май", external_reference="KTZ-2025-118", actor=user,
        )
        record_shipment_expense(
            account=kgs_bank, amount=D("240000"), effective_date=date(2025, 7, 16),
            category=customs, shipment=july, note="Таможня и брокер, июльская партия", external_reference="CUS-2025-077", actor=user,
        )
        duplicate = record_shipment_expense(
            account=kgs_bank, amount=D("99000"), effective_date=date(2025, 11, 26),
            category=rail, shipment=november, note="ЖД тариф, ноябрь — провели дважды", external_reference="KTZ-2025-311", actor=user,
        )
        reverse_document(duplicate.document, effective_date=date(2025, 11, 27), note="Дубль платежа за ноябрь, снят", actor=user)
        record_shipment_expense(
            account=kgs_bank, amount=D("310000"), effective_date=date(2025, 11, 28),
            category=rail, shipment=november, note="ЖД тариф, 4 вагона, ноябрь", external_reference="KTZ-2025-312", actor=user,
        )
        record_shipment_expense(
            account=cash, amount=D("18500"), effective_date=date(2025, 9, 22),
            category=rail, shipment=july, note="Доплата бригаде за разгрузку, сентябрь", external_reference="CASH-2025-0922", actor=user,
        )
        settle_supplier(
            party=kaz, effective_date=date(2025, 12, 1),
            allocations=[{"order": spec_old_1, "amount": D("40000")}],
            note="Зачёт предоплаты KZ-2025/04 в спецификацию 1", actor=user,
        )
        self._pay(
            pay, kaz, usd, "100000", date(2025, 12, 5),
            "Оплата спецификации 1, остаток долга не закрыт", "SWIFT-2025-1205", user, order=spec_old_1,
        )
        old.active = False
        old.save()

        fresh = record_contract(
            supplier=astyk,
            number="AST-2026/02",
            contract_date=date(2026, 2, 12),
            currency="KZT",
            delivery_term=fca,
            end_date=date(2027, 2, 11),
            volume_tons=D("1500"),
            amount_limit=D("75000000"),
            prepayment_percent=D("30"),
            payment_terms="30% предоплата, остаток 10 дней после приёмки на станции Манас",
            description="Пшеница 3 и 4 класса. Отгрузка FCA, приёмка Манас.",
        )
        spec_kzt_1 = self._spec(
            astyk, fresh, "1", date(2026, 2, 20), wheat3, "800000", "47.5000", "KZT", fca, "800 т пшеницы 3 класса."
        )
        self._spec(
            astyk, fresh, "2", date(2026, 10, 5), wheat4, "400000", "49.0000", "KZT", fca,
            "План на 400 т 4 класса. Поставок ещё нет.",
        )
        self._pay(pay, astyk, kzt, "10000000", date(2026, 2, 25), "Предоплата 30% по AST-2026/02", "KZT-2026-0225", user)
        april = self._ship(
            spec_kzt_1, petropavlovsk, manas, date(2026, 4, 3), date(2026, 4, 16),
            [("54260401", "68500"), ("54260402", "69200"), ("54260403", "70300")],
            "Апрель, Петропавловск", elevator, user,
        )
        self._ship(
            spec_kzt_1, karaganda, manas, date(2026, 6, 8), date(2026, 6, 19),
            [("54260601", "67000"), ("54260602", "71000")],
            "Июнь, Караганда", elevator, user,
        )
        self._ship(
            spec_kzt_1, astana, manas, date(2026, 8, 21), date(2026, 9, 2),
            [("54260801", "66000"), ("54260802", "66000"), ("54260803", "66000"), ("54260804", "66000")],
            "Август, Астана, 4 вагона", elevator, user,
        )
        self._ship(
            spec_kzt_1, kok, manas, date(2026, 11, 18), date(2026, 11, 23),
            [("54261101", "68500")],
            "Прибыл на Манас. В накладной 2 вагона и 140 т, второй номер ещё не внесён.",
            elevator, user, post=False, wagon_count=2, quantity=D("140000"), complete=False,
        )
        record_shipment_expense(
            account=kgs_bank, amount=D("274600"), effective_date=date(2026, 4, 18),
            category=rail, shipment=april, note="ЖД тариф, Петропавловск — Манас", external_reference="KTZ-2026-0418", actor=user,
        )
        settle_supplier(
            party=astyk, effective_date=date(2026, 9, 10),
            allocations=[{"order": spec_kzt_1, "amount": D("10000000")}],
            note="Зачёт предоплаты AST-2026/02 в спецификацию 1", actor=user,
        )
        self._pay(
            pay, astyk, kzt, "8000000", date(2026, 9, 15),
            "Частичная оплата спецификации 1", "KZT-2026-0915", user, order=spec_kzt_1,
        )

        current = PurchaseOrder.objects.get(contract__number="KZ-2026/15", specification_number="1")
        self._ship(
            current, kok, manas, date(2026, 11, 20), None,
            [("95126001", "68400"), ("95126002", "68100"), ("95126003", "68500")],
            "В пути на Манас. Вагоны сверены, дату приёмки поставим по прибытии.",
            elevator, user, post=False,
        )

        self._buy_flow(rakhimov, mat_wh, premix, oil, user, pay, kgs_bank)
        self._sack_flow(sibagro, pack_wh, sack50, sack25, user, pay, kgs_bank, cash)
        self._flour_flow(dan, flour_wh, flour_bars, flour25, flour_hs, bran, user, pay, kgs_bank)
        self._sales(aigul, nurlan, altyn, flour_wh, flour_bars, flour25, flour_hs, user, receive, kgs_bank)

        record_money(
            operation=electricity, account=kgs_bank, amount=D("42800"), effective_date=date(2026, 1, 12),
            note="Электричество, январь", external_reference="EL-2026-01", actor=user,
        )
        record_money(
            operation=tax, account=kgs_bank, amount=D("125000"), effective_date=date(2026, 4, 15),
            note="Налог за 1 квартал", external_reference="TAX-2026-Q1", actor=user,
        )
        held = record_money(
            operation=advance, account=cash, amount=D("20000"), effective_date=date(2026, 10, 6),
            party=bakyt, note="На разгрузку вагонов", external_reference="CASH-POD-1006", actor=user,
        )
        recognize_accountable(
            advance=held.document.open_items.get(), operation=unloading, amount=D("12000"),
            effective_date=date(2026, 10, 9), shipment=april,
            note="Разгрузка апрельской партии, закрыто по чекам", actor=user,
        )
        record_money(
            operation=give_back, account=cash, amount=D("3000"), effective_date=date(2026, 10, 21),
            party=bakyt, note="Сдал остаток в кассу", external_reference="CASH-POD-1021", actor=user,
        )
        record_money(
            operation=deposit, account=cash, counter_account=kgs_bank, amount=D("80000"),
            effective_date=date(2026, 11, 1), note="Сдача выручки в банк", actor=user,
        )

    def _product(self, sku, name, kind, category, unit, weight):
        product = save_product(sku=sku, name=name, category=category, unit=unit, unit_weight_kg=weight)
        product.kind = kind
        product.save()
        return product

    def _station(self, name, code, country):
        return RailwayStation.objects.create(name=name, station_code=code, country=country, active=True)

    def _spec(self, supplier, contract, number, when, product, qty, price, currency, term, note):
        return record_purchase(
            supplier=supplier,
            effective_date=when,
            lines=[{"product": product, "quantity": D(qty), "price": D(price)}],
            note=note,
            contract=contract,
            specification_number=number,
            currency=currency,
            delivery_term=term,
            tolerance_percent=D("5"),
        )

    def _ship(
        self, order, origin, destination, departed, arrived, wagons, note, warehouse, actor,
        post=True, wagon_count=None, quantity=None, complete=True,
    ):
        weights = [D(weight) for _number, weight in wagons]
        qty = quantity if quantity is not None else sum(weights, D("0"))
        count = wagon_count or len(wagons)
        shipment = record_shipment(
            order=order,
            quantity=qty,
            departure_date=departed,
            arrival_date=arrived,
            notes=note,
            departure_station=origin,
            destination_station=destination,
            wagon_count=count,
            actor=actor,
        )
        declare_wagons(
            shipment,
            [{"wagon_number": number, "weight_kg": D(weight)} for number, weight in wagons],
            complete=complete,
            actor=actor,
        )
        if post:
            post_shipment(shipment, warehouse=warehouse, actor=actor)
        return shipment

    def _pay(self, operation, party, account, amount, when, note, reference, actor, order=None):
        kwargs = {}
        if order is not None:
            kwargs["allocations"] = [{"order": order, "amount": D(amount)}]
        return record_money(
            operation=operation,
            account=account,
            amount=D(amount),
            effective_date=when,
            party=party,
            note=note,
            external_reference=reference,
            actor=actor,
            **kwargs,
        )

    def _order(self, supplier, when, product, qty, price, note, bags=None):
        return record_purchase(
            supplier=supplier,
            effective_date=when,
            lines=[{"product": product, "quantity": D(qty), "price": D(price), "bags": bags}],
            note=note,
        )

    def _receive(self, supplier, warehouse, when, order, qty, note, bags=None):
        line = order.lines.get()
        return record_receipt(
            supplier=supplier,
            warehouse=warehouse,
            effective_date=when,
            lines=[{
                "product": line.product,
                "quantity": D(qty),
                "purchase_line": line,
                "bags": bags,
            }],
            note=note,
        )

    def _buy_flow(self, rakhimov, warehouse, premix, oil, actor, pay, bank):
        first = self._order(rakhimov, date(2025, 6, 10), premix, "500", "380", "Премикс на лето")
        self._receive(rakhimov, warehouse, date(2025, 6, 12), first, "500", "Пришло полностью")
        self._pay(pay, rakhimov, bank, "190000", date(2025, 6, 20), "Оплата премикса, июнь", "PP-2025-0620", actor, first)

        second = self._order(rakhimov, date(2025, 11, 3), premix, "1200", "395", "Зимний запас, примут частями")
        self._receive(rakhimov, warehouse, date(2025, 11, 8), second, "800", "Пришло 800 кг из 1 200")
        self._pay(pay, rakhimov, bank, "200000", date(2025, 11, 20), "Частичная оплата, долг остался", "PP-2025-1120", actor, second)

        oil_order = self._order(rakhimov, date(2026, 3, 16), oil, "600", "145", "Масло подсолнечное, 600 л")
        self._receive(rakhimov, warehouse, date(2026, 3, 18), oil_order, "600", "Масло приняли, счёт не оплачен")

        self._order(rakhimov, date(2026, 9, 1), premix, "400", "410", "Заказано, машину ещё не приняли")

        returned = self._order(rakhimov, date(2026, 10, 22), premix, "250", "410", "Пришло не то, вернули")
        receipt = self._receive(rakhimov, warehouse, date(2026, 10, 24), returned, "250", "Приёмка, потом возврат")
        reverse_document(
            receipt.document,
            effective_date=date(2026, 10, 27),
            note="Вернули: привезли другой премикс, ждём замену",
            actor=actor,
        )

    def _sack_flow(self, sibagro, warehouse, sack50, sack25, actor, pay, bank, cash):
        open_order = PurchaseOrder.objects.get(document__number="PUR-000004")
        self._receive(sibagro, warehouse, date(2026, 11, 24), open_order, "500", "500 мешков по заказу PUR-000004")
        self._pay(pay, sibagro, cash, "3000", date(2026, 11, 24), "Часть оплаты из кассы, долг 2 000", "CASH-2026-1124", actor, open_order)

        old = self._order(sibagro, date(2025, 9, 4), sack50, "8000", "9.50", "Мешки 50 кг на осень")
        self._receive(sibagro, warehouse, date(2025, 9, 10), old, "8000", "Пришло полностью")
        self._pay(pay, sibagro, bank, "76000", date(2025, 9, 18), "Оплата 8 000 мешков", "PP-2025-0918", actor, old)

        winter = self._order(sibagro, date(2026, 1, 22), sack50, "15000", "10.50", "Запас мешков на весну")
        self._receive(sibagro, warehouse, date(2026, 1, 29), winter, "15000", "Пришло полностью")
        self._pay(pay, sibagro, bank, "100000", date(2026, 2, 5), "Оплатили не всё, остаток висит", "PP-2026-0205", actor, winter)

        august = self._order(sibagro, date(2026, 8, 11), sack25, "6000", "11", "Мешки 25 кг под муку 1 сорта")
        self._receive(sibagro, warehouse, date(2026, 8, 14), august, "6000", "Приняли, счёт не оплачен")

        self._order(sibagro, date(2026, 11, 2), sack25, "2000", "11.50", "Дозаказ. Машины ещё нет, приёмки нет")

    def _flour_flow(self, dan, warehouse, bars, flour25, flour_hs, bran, actor, pay, bank):
        bars_order = self._order(dan, date(2026, 2, 6), bars, "400", "1750", "Мука Барс, 400 мешков по 50 кг")
        self._receive(dan, warehouse, date(2026, 2, 10), bars_order, "400", "400 мешков на склад муки")
        self._pay(pay, dan, bank, "400000", date(2026, 2, 18), "Оплатили часть, долг остался", "PP-2026-0218", actor, bars_order)

        hs = self._order(dan, date(2026, 4, 7), flour_hs, "2500", "31.50", "Высший сорт, 50 мешков по 50 кг", bags=50)
        self._receive(dan, warehouse, date(2026, 4, 9), hs, "2500", "2 500 кг высшего сорта", bags=50)
        self._pay(pay, dan, bank, "78750", date(2026, 4, 14), "Оплатили высший сорт полностью", "PP-2026-0414", actor, hs)

        small = self._order(dan, date(2026, 5, 18), flour25, "800", "690", "Мука 1 сорт, мешок 25 кг")
        self._receive(dan, warehouse, date(2026, 5, 21), small, "800", "800 мешков")
        self._pay(pay, dan, bank, "552000", date(2026, 5, 28), "Оплата муки 1 сорта", "PP-2026-0528", actor, small)

        bran_order = self._order(dan, date(2026, 6, 20), bran, "8000", "8.50", "Отруби на перепродажу")
        self._receive(dan, warehouse, date(2026, 6, 22), bran_order, "8000", "8 т отрубей, счёт открыт")

    def _sales(self, aigul, nurlan, altyn, warehouse, bars, flour25, flour_hs, actor, receive, bank):
        spring = record_sale(
            customer=aigul, effective_date=date(2026, 3, 2),
            lines=[{"product": bars, "quantity": D("180"), "price": D("2100")}],
            note="Пекарня Айгуль, 180 мешков Барс", actor=actor,
        )
        self._issue(aigul, warehouse, date(2026, 3, 3), spring, "180", "Отгрузили всё")
        record_money(
            operation=receive, account=bank, amount=D("378000"), effective_date=date(2026, 3, 10),
            party=aigul, note="Айгуль закрыла счёт", external_reference="IN-2026-0310", actor=actor,
        )

        summer = record_sale(
            customer=aigul, effective_date=date(2026, 8, 19),
            lines=[{"product": bars, "quantity": D("120"), "price": D("2150")}],
            note="Айгуль, август. Отгрузили не всё.", actor=actor,
        )
        self._issue(aigul, warehouse, date(2026, 8, 20), summer, "80", "Отгрузили 80 из 120 мешков")

        nurlan_sale = record_sale(
            customer=nurlan, effective_date=date(2026, 6, 2),
            lines=[{"product": flour25, "quantity": D("500"), "price": D("860")}],
            note="Нурлан-Нан, мука 1 сорт", actor=actor,
        )
        self._issue(nurlan, warehouse, date(2026, 6, 4), nurlan_sale, "500", "500 мешков уехали")
        record_money(
            operation=receive, account=bank, amount=D("200000"), effective_date=date(2026, 6, 15),
            party=nurlan, note="Частичная оплата, остаток долга", external_reference="IN-2026-0615", actor=actor,
        )

        hs_sale = record_sale(
            customer=altyn, effective_date=date(2026, 7, 9),
            lines=[{"product": flour_hs, "quantity": D("1500"), "price": D("42"), "bags": 30}],
            note="Алтын Дан, высший сорт в Бишкек. Не оплачено.", actor=actor,
        )
        self._issue(altyn, warehouse, date(2026, 7, 11), hs_sale, "1500", "1 500 кг, 30 мешков", bags=30)

    def _issue(self, customer, warehouse, when, sale, qty, note, bags=None):
        line = sale.lines.get()
        record_issue(
            customer=customer,
            warehouse=warehouse,
            effective_date=when,
            lines=[{"product": line.product, "quantity": D(qty), "sale_line": line, "bags": bags}],
            note=note,
        )
