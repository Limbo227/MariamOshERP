from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.catalog.models import Product
from apps.core.models import Company


class PurchaseOrder(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        CONFIRMED = "CONFIRMED", "Подтверждён"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT)
    currency = models.CharField("Валюта", max_length=3, default="KGS")
    reference = models.CharField("Основание", max_length=160)
    contract_reference = models.CharField("Договор", max_length=80, blank=True)
    batch_number = models.CharField("Партия", max_length=80, blank=True)
    wagon_count = models.PositiveIntegerField("Вагоны", null=True, blank=True)
    effective_date = models.DateField("Дата")
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT)
    delivery_closed = models.BooleanField("Поставка закрыта", default=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders_created")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="orders_confirmed")
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="unique_order_key"),
            models.CheckConstraint(condition=Q(currency="KGS"), name="order_currency_kgs"),
            models.CheckConstraint(condition=Q(wagon_count__isnull=True) | Q(wagon_count__gt=0), name="wagon_count_positive"),
        ]
        ordering = ["-effective_date", "-pk"]
        permissions = [
            ("confirm_purchaseorder", "Подтверждение заказа поставщику"),
            ("amend_purchaseorder", "Изменение согласованной суммы"),
            ("view_purchaseprice", "Просмотр цен поставщика"),
        ]
        verbose_name = "Заказ поставщику"
        verbose_name_plural = "Заказы поставщикам"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = PurchaseOrder.objects.get(pk=self.pk)
            if previous.state == self.State.CONFIRMED:
                protected = ("company_id", "supplier_id", "currency", "reference", "contract_reference", "batch_number", "wagon_count", "effective_date", "key", "state", "actor_id")
                if any(getattr(previous, field) != getattr(self, field) for field in protected):
                    raise ValidationError("Подтверждённый заказ не переписывается.")
        return super().save(*args, **kwargs)

    def journey(self):
        if self.state != self.State.CONFIRMED:
            return "Заявка"
        stored = getattr(self, "stored_qty", None)
        customs = getattr(self, "customs_qty", None)
        if stored is None:
            from apps.inventory.models import GoodsReceipt

            stored = GoodsReceipt.objects.filter(order=self, state=GoodsReceipt.State.POSTED).exists()
            customs = self.acceptances.exists()
            if stored:
                return "На складе"
            if customs:
                return "Прибыло в таможню"
            return "Отправлено"
        if stored > 0:
            return "На складе"
        if customs > 0:
            return "Прибыло в таможню"
        return "Отправлено"

    def __str__(self):
        return self.reference


class OrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    unit = models.CharField(max_length=3)
    unit_price = models.DecimalField("Цена", max_digits=18, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_order_quantity")]
        verbose_name = "Строка заказа"
        verbose_name_plural = "Строки заказа"

    def clean(self):
        if self.product_id and self.order_id and self.product.company_id != self.order.company_id:
            raise ValidationError("Товар относится к другому предприятию.")
        if self.product_id and self.product.is_finished:
            raise ValidationError("В заказ поставщику не входит готовая продукция.")
        if self.unit_price is not None and self.unit_price <= 0:
            raise ValidationError("Согласованная цена должна быть больше нуля.")

    def save(self, *args, **kwargs):
        if self.order_id and self.order.state == PurchaseOrder.State.CONFIRMED:
            raise ValidationError("Подтверждённый заказ не переписывается.")
        if self.product_id and not self.unit:
            self.unit = self.product.unit
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product} — {self.quantity}"


class OrderAmendment(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="amendments")
    revision = models.PositiveIntegerField()
    reason = models.CharField("Причина", max_length=200)
    effective_date = models.DateField("Дата")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "revision"], name="unique_order_revision")]
        ordering = ["revision"]
        verbose_name = "Изменение заказа"
        verbose_name_plural = "Изменения заказа"

    def __str__(self):
        return f"{self.order} / {self.revision}"


class AmendmentLine(models.Model):
    amendment = models.ForeignKey(OrderAmendment, on_delete=models.PROTECT, related_name="lines")
    order_line = models.ForeignKey(OrderLine, on_delete=models.PROTECT)
    new_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    new_price = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["amendment", "order_line"], name="unique_amendment_line"),
            models.CheckConstraint(condition=Q(new_quantity__gt=0, new_price__gt=0), name="positive_amended_terms"),
        ]

    def clean(self):
        if self.order_line_id and self.amendment_id and self.order_line.order_id != self.amendment.order_id:
            raise ValidationError("Строка не относится к этому заказу.")


class CustomsAcceptance(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="acceptances")
    port = models.CharField("Таможенный пост", max_length=80)
    quantity = models.DecimalField("Принято", max_digits=18, decimal_places=3)
    accepted_on = models.DateField("Дата")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_customs_quantity")]
        ordering = ["accepted_on", "pk"]
        verbose_name = "Отметка таможни"
        verbose_name_plural = "Отметки таможни"

    def __str__(self):
        return f"{self.port} {self.quantity}"


class Shipment(models.Model):
    class State(models.TextChoices):
        PLANNED = "PLANNED", "В пути"
        IN_CUSTOMS = "IN_CUSTOMS", "На таможне"
        ARRIVED = "ARRIVED", "Прибыло"
        CLOSED = "CLOSED", "Поставка закрыта"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT)
    order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT)
    reference = models.CharField("Партия поставщика", max_length=80)
    customs_port = models.CharField("Таможня", max_length=80, blank=True)
    expected_date = models.DateField("Ожидается", null=True, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PLANNED)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Поставка"
        verbose_name_plural = "Поставки"

    def clean(self):
        if self.order_id and (self.order.company_id != self.company_id or self.order.supplier_id != self.supplier_id):
            raise ValidationError("Поставка должна относиться к тому же поставщику и предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.reference


class TransportUnit(models.Model):
    class Kind(models.TextChoices):
        WAGON = "WAGON", "Вагон"
        TRUCK = "TRUCK", "Автомобиль"
        OTHER = "OTHER", "Другое"

    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="units")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.WAGON)
    identifier = models.CharField("Номер", max_length=40)
    declared_quantity = models.DecimalField("Заявлено", max_digits=18, decimal_places=3)
    order_line = models.ForeignKey(OrderLine, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shipment", "identifier"], name="unique_shipment_unit"),
            models.CheckConstraint(condition=Q(declared_quantity__gt=0), name="positive_declared_quantity"),
        ]
        verbose_name = "Транспорт"
        verbose_name_plural = "Транспорт"

    def clean(self):
        if self.order_line_id and self.shipment_id and self.order_line.order_id != self.shipment.order_id:
            raise ValidationError("Строка заказа не относится к этой поставке.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.identifier


class PurchaseCharge(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="charges")
    counterparty = models.CharField("Кому", max_length=160)
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KGS")
    charged_on = models.DateField("Дата")
    note = models.CharField("Назначение", max_length=160, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="positive_charge"),
            models.CheckConstraint(condition=Q(currency="KGS"), name="charge_currency_kgs"),
        ]
        verbose_name = "Расход на поставку"
        verbose_name_plural = "Расходы на поставку"

    def __str__(self):
        return f"{self.counterparty} {self.amount}"


class ChargePayment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Касса"
        BANK = "BANK", "Банк"

    charge = models.ForeignKey(PurchaseCharge, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=8, choices=Method.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    paid_on = models.DateField()
    reference = models.CharField("Ссылка", max_length=80, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="positive_charge_payment")]
        verbose_name = "Оплата расхода"
        verbose_name_plural = "Оплаты расходов"


class Attachment(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT)
    shipment = models.ForeignKey(Shipment, null=True, blank=True, on_delete=models.PROTECT)
    receipt = models.ForeignKey("inventory.GoodsReceipt", null=True, blank=True, on_delete=models.PROTECT)
    filename = models.CharField("Файл", max_length=160)
    storage_key = models.CharField(max_length=80)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Вложение"
        verbose_name_plural = "Вложения"

    def clean(self):
        parents = [self.order_id, self.shipment_id, self.receipt_id]
        if sum(bool(item) for item in parents) != 1:
            raise ValidationError("Вложение относится ровно к одному документу.")
        parent_company = None
        if self.order_id:
            parent_company = self.order.company_id
        elif self.shipment_id:
            parent_company = self.shipment.company_id
        elif self.receipt_id:
            parent_company = self.receipt.company_id
        if parent_company != self.company_id:
            raise ValidationError("Вложение относится к другому предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SupplyContract(models.Model):
    """Commercial agreement. The goods sit on the lines below it, like a document cart."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT, related_name="contracts")
    number = models.CharField("Номер контракта", max_length=80)
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    key = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="unique_contract_key"),
            models.UniqueConstraint(fields=["company", "supplier", "number"], name="unique_supplier_contract_number"),
            models.CheckConstraint(condition=Q(currency="RUB"), name="supply_contract_currency_rub"),
        ]
        ordering = ["supplier__name", "pk"]
        verbose_name = "Контракт"
        verbose_name_plural = "Контракты"

    def clean(self):
        if self.supplier_id and self.company_id and self.supplier.company_id != self.company_id:
            raise ValidationError("Поставщик относится к другому предприятию.")
        if self.supplier_id and not self.supplier.is_supplier:
            raise ValidationError("Контракт можно заключить только с поставщиком.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class ContractLine(models.Model):
    contract = models.ForeignKey(SupplyContract, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    price = models.DecimalField("Цена", max_digits=18, decimal_places=4)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0, price__gt=0), name="positive_contract_line")]
        ordering = ["position", "pk"]
        verbose_name = "Строка контракта"
        verbose_name_plural = "Строки контракта"

    def clean(self):
        if self.product_id and self.contract_id and self.product.company_id != self.contract.company_id:
            raise ValidationError("Товар относится к другому предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def amount(self):
        return (self.quantity * self.price).quantize(Decimal("0.01"))


class ContractShipment(models.Model):
    """One dispatch under a contract line. The arrival date is recorded separately at the factory."""

    line = models.ForeignKey(ContractLine, on_delete=models.PROTECT, related_name="shipments")
    station = models.ForeignKey("catalog.OriginStation", on_delete=models.PROTECT)
    wagon_count = models.PositiveIntegerField("Вагоны")
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    key = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key"], name="unique_contract_shipment_key"),
            models.CheckConstraint(condition=Q(wagon_count__gt=0, quantity__gt=0), name="positive_contract_shipment"),
        ]
        ordering = ["pk"]
        verbose_name = "Отгрузка"
        verbose_name_plural = "Отгрузки"

    def clean(self):
        if self.station_id and self.line_id and self.station.company_id != self.line.contract.company_id:
            raise ValidationError("Станция относится к другому предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def amount(self):
        return (self.quantity * self.line.price).quantize(Decimal("0.01"))


class FactoryArrival(models.Model):
    shipment = models.OneToOneField(ContractShipment, on_delete=models.PROTECT, related_name="factory_arrival")
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT)
    arrived_on = models.DateField("Дата прибытия")
    key = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key"], name="unique_factory_arrival_key")]
        verbose_name = "Прибытие на завод"
        verbose_name_plural = "Прибытия на завод"

    def clean(self):
        if self.warehouse_id and self.shipment_id and self.warehouse.company_id != self.shipment.line.contract.company_id:
            raise ValidationError("Склад относится к другому предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ContractPayment(models.Model):
    contract = models.ForeignKey(SupplyContract, on_delete=models.PROTECT, related_name="bank_payments")
    paid_on = models.DateField("Дата оплаты")
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)
    key = models.UUIDField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key"], name="unique_contract_payment_key"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="positive_contract_payment"),
        ]
        ordering = ["paid_on", "pk"]
        verbose_name = "Оплата по контракту"
        verbose_name_plural = "Оплаты по контрактам"
