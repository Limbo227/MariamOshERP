from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Currency, FrozenLine
from apps.core.quantities import line_amount


class DeliveryTerm(models.Model):
    code = models.CharField("Код", max_length=40, unique=True)
    name = models.CharField("Название", max_length=120)
    description = models.TextField("Описание", blank=True)
    active = models.BooleanField("Действует", default=True)

    class Meta:
        db_table = "delivery_term"
        ordering = ["name"]
        verbose_name = "Условие поставки"
        verbose_name_plural = "Условия поставки"

    def __str__(self):
        return self.name


class RailwayStation(models.Model):
    name = models.CharField("Название", max_length=160)
    station_code = models.CharField("Код станции", max_length=40, blank=True)
    country = models.CharField("Страна", max_length=80, blank=True)
    active = models.BooleanField("Действует", default=True)

    class Meta:
        db_table = "railway_station"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["station_code"],
                condition=~Q(station_code=""),
                name="station_code_unique",
            ),
        ]
        verbose_name = "Железнодорожная станция"
        verbose_name_plural = "Железнодорожные станции"

    def clean(self):
        self.name = (self.name or "").strip()
        self.station_code = (self.station_code or "").strip()
        if not self.name:
            raise ValidationError("Укажите название станции.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PurchaseContract(models.Model):
    supplier = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="purchase_contracts")
    number = models.CharField("Номер", max_length=40)
    contract_date = models.DateField("Дата")
    currency = models.CharField("Валюта", max_length=3, choices=Currency.choices, default=Currency.KGS)
    delivery_term = models.ForeignKey(
        DeliveryTerm,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Условие поставки",
    )
    description = models.TextField("Описание", blank=True)
    active = models.BooleanField("Действует", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "purchase_contract"
        constraints = [
            models.UniqueConstraint(fields=["supplier", "number"], name="contract_supplier_number"),
            models.CheckConstraint(condition=Q(currency__in=["KGS", "RUB", "USD", "KZT"]), name="contract_currency"),
        ]
        verbose_name = "Договор закупки"
        verbose_name_plural = "Договоры закупки"

    def clean(self):
        self.number = (self.number or "").strip()
        if not self.number:
            raise ValidationError("У договора нужен номер.")
        if self.supplier_id and self.number:
            clash = PurchaseContract.objects.filter(supplier_id=self.supplier_id, number=self.number)
            if self.pk:
                clash = clash.exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError("У этого поставщика уже есть договор с таким номером.")
        if self.supplier_id and not self.supplier.is_supplier:
            raise ValidationError("Договор оформляется на поставщика.")
        if self.currency not in Currency.values:
            raise ValidationError("Валюта договора должна быть KGS, RUB, USD или KZT.")
        if self.pk:
            previous = PurchaseContract.objects.get(pk=self.pk)
            if self.specifications.exists() and (
                previous.supplier_id != self.supplier_id or previous.number != self.number
            ):
                raise ValidationError("У договора со спецификациями нельзя менять поставщика или номер.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class PurchaseOrder(models.Model):
    class Currency(models.TextChoices):
        KGS = "KGS", "KGS"
        RUB = "RUB", "RUB"
        USD = "USD", "USD"
        KZT = "KZT", "KZT"

    class OperationalStatus(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "В работе"
        COMPLETED = "COMPLETED", "Выполнено"

    document = models.OneToOneField("core.Document", on_delete=models.PROTECT, related_name="purchase")
    supplier = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="purchases")
    contract = models.ForeignKey(
        PurchaseContract,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="specifications",
        verbose_name="Договор",
    )
    specification_number = models.CharField("Номер спецификации", max_length=40, blank=True)
    currency = models.CharField("Валюта", max_length=3, choices=Currency.choices, default=Currency.KGS)
    delivery_term = models.ForeignKey(
        DeliveryTerm,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="specifications",
        verbose_name="Условие поставки",
    )
    tolerance_percent = models.DecimalField(
        "Допуск, %", max_digits=6, decimal_places=2, default=Decimal("0")
    )
    operational_status = models.CharField(
        "Состояние поставки",
        max_length=16,
        choices=OperationalStatus.choices,
        default=OperationalStatus.IN_PROGRESS,
    )

    class Meta:
        db_table = "purchase_order"
        constraints = [
            models.CheckConstraint(condition=Q(currency__in=["KGS", "RUB", "USD", "KZT"]), name="purchase_currency"),
            models.CheckConstraint(condition=Q(tolerance_percent__gte=0), name="purchase_tolerance"),
            models.CheckConstraint(
                condition=Q(operational_status__in=["IN_PROGRESS", "COMPLETED"]),
                name="purchase_operational_status",
            ),
            models.UniqueConstraint(
                fields=["contract", "specification_number"],
                condition=Q(contract__isnull=False),
                name="specification_in_contract",
            ),
        ]
        verbose_name = "Закупка"
        verbose_name_plural = "Закупки"

    def save(self, *args, **kwargs):
        from apps.core.lifecycle import lifecycle_open
        from apps.core.models import Document

        if self.pk and not lifecycle_open():
            previous = PurchaseOrder.objects.get(pk=self.pk)
            locked = ("document_id", "supplier_id", "contract_id", "specification_number", "currency")
            if any(getattr(previous, field) != getattr(self, field) for field in locked):
                if self.document.state != Document.State.DRAFT:
                    raise ValidationError(
                        "Проведённую спецификацию нельзя так изменить. Сначала отмените выполнение."
                    )
        if not self.pk and self.document.state != Document.State.DRAFT:
            raise ValidationError("Закупка создаётся до проведения.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        if self.supplier_id and not self.supplier.is_supplier:
            raise ValidationError("Закупка оформляется на поставщика.")
        self.specification_number = (self.specification_number or "").strip()
        if self.contract_id:
            if self.pk is None and not self.contract.active:
                raise ValidationError("Договор не действует.")
            if self.contract.supplier_id != self.supplier_id:
                raise ValidationError("Поставщик закупки должен совпадать с поставщиком договора.")
            if not self.specification_number:
                raise ValidationError("Для спецификации нужен номер в рамках договора.")
            clash = PurchaseOrder.objects.filter(
                contract_id=self.contract_id, specification_number=self.specification_number
            )
            if self.pk:
                clash = clash.exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError("Номер спецификации уже есть в этом договоре.")
        elif self.specification_number:
            raise ValidationError("Номер спецификации указывают только для закупки по договору.")
        if self.tolerance_percent is not None and self.tolerance_percent < 0:
            raise ValidationError("Допуск не может быть отрицательным.")

    def __str__(self):
        return str(self.document)


class PurchaseLine(FrozenLine):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="purchase_lines")
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    price = models.DecimalField("Цена", max_digits=18, decimal_places=4)
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)

    class Meta:
        db_table = "purchase_line"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="purchase_qty"),
            models.CheckConstraint(condition=Q(price__gt=0), name="purchase_price"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="purchase_amount"),
        ]
        verbose_name = "Строка закупки"
        verbose_name_plural = "Строки закупки"

    def document_for_edit(self):
        return self.order.document

    def clean(self):
        from apps.inventory.checks import ensure_packaging

        ensure_packaging(self.product, self.quantity, self.bags)
        if self.quantity and self.price and self.amount != line_amount(self.quantity, self.price):
            raise ValidationError("Сумма строки должна равняться количеству, умноженному на цену.")


class Shipment(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Выполнено"

    # Kept as `status` so existing screens keep reading get_status_display.
    Status = State

    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="shipments")
    departure_station = models.ForeignKey(
        RailwayStation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="shipments",
        verbose_name="Станция отправления",
    )
    departure_date = models.DateField("Дата отправления", null=True, blank=True)
    arrival_date = models.DateField("Дата приёмки", null=True, blank=True)
    wagon_count = models.PositiveIntegerField("Число вагонов", default=1)
    quantity = models.DecimalField("Вес нетто, кг", max_digits=18, decimal_places=3)
    notes = models.TextField("Заметка", blank=True)
    status = models.CharField("Состояние", max_length=16, choices=State.choices, default=State.DRAFT)
    details_complete = models.BooleanField("Вагоны сверены", default=False)
    receipt = models.OneToOneField(
        "inventory.GoodsReceipt",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_shipment",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "shipment"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="shipment_qty"),
            models.CheckConstraint(condition=Q(wagon_count__gte=1), name="shipment_wagon_count"),
            models.CheckConstraint(condition=Q(status__in=["DRAFT", "POSTED"]), name="shipment_status"),
            models.CheckConstraint(
                condition=Q(status="DRAFT", receipt__isnull=True, posted_at__isnull=True)
                | Q(status="POSTED", receipt__isnull=False, posted_at__isnull=False),
                name="shipment_posted_receipt",
            ),
        ]
        verbose_name = "Поставка"
        verbose_name_plural = "Поставки"

    def clean(self):
        from apps.core.models import Document

        if self.order_id and self.order.document.state != Document.State.POSTED:
            raise ValidationError("Отгрузку регистрируют по проведённой закупке.")
        if self.arrival_date and self.departure_date and self.arrival_date < self.departure_date:
            raise ValidationError("Дата приёмки не может быть раньше даты отправления.")
        if not self.pk and not self.departure_station_id:
            raise ValidationError("Укажите станцию отправления.")
        if self.status == self.State.POSTED and not self.departure_station_id:
            raise ValidationError("У проведённой поставки нужна станция отправления.")
        if self.wagon_count < 1:
            raise ValidationError("Число вагонов должно быть больше нуля.")
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError("Вес поставки должен быть больше нуля.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def wagon_number(self):
        if not self.pk:
            return ""
        wagons = list(self.wagons.all())
        if len(wagons) == 1:
            return wagons[0].wagon_number
        return ""

    def __str__(self):
        label = self.wagon_number
        if label:
            return label
        return f"Поставка {self.pk or ''}".strip()


class ShipmentWagon(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="wagons")
    wagon_number = models.CharField("Номер вагона", max_length=40)
    weight_kg = models.DecimalField("Вес, кг", max_digits=18, decimal_places=3)

    class Meta:
        db_table = "shipment_wagon"
        constraints = [
            models.UniqueConstraint(fields=["shipment", "wagon_number"], name="wagon_number_in_shipment"),
            models.CheckConstraint(condition=Q(weight_kg__gt=0), name="wagon_weight_positive"),
        ]
        ordering = ["pk"]
        verbose_name = "Вагон поставки"
        verbose_name_plural = "Вагоны поставки"

    def clean(self):
        self.wagon_number = (self.wagon_number or "").strip()
        if not self.wagon_number:
            raise ValidationError("Укажите номер вагона.")
        if self.weight_kg is None or self.weight_kg <= 0:
            raise ValidationError("Вес вагона должен быть больше нуля.")
        if self.shipment_id and self.wagon_number:
            clash = ShipmentWagon.objects.filter(shipment_id=self.shipment_id, wagon_number=self.wagon_number)
            if self.pk:
                clash = clash.exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError("Номер вагона повторяется в поставке.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.wagon_number
