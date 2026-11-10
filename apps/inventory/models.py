from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.catalog.models import Product
from apps.core.models import Company


class Warehouse(models.Model):
    class Kind(models.TextChoices):
        RAW = "RAW", "Сырьё"
        FINISHED = "FINISHED", "Готовая продукция"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    name = models.CharField("Название", max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "kind"], name="unique_warehouse_kind"),
            models.CheckConstraint(condition=Q(kind__in=["RAW", "FINISHED"]), name="valid_warehouse_kind"),
        ]
        ordering = ["kind"]
        verbose_name = "Склад"
        verbose_name_plural = "Склады"

    def __str__(self):
        return self.name


class StorageLocation(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    name = models.CharField("Название", max_length=80)
    active = models.BooleanField("Активно", default=True)
    is_default = models.BooleanField("Основное место", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "name"], name="unique_location_name"),
            models.UniqueConstraint(fields=["warehouse"], condition=Q(is_default=True), name="one_default_location"),
        ]
        ordering = ["name"]
        verbose_name = "Место хранения"
        verbose_name_plural = "Места хранения"

    def __str__(self):
        return self.name


class OpeningBalance(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Подтверждён"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64, blank=True)
    reference = models.CharField("Основание", max_length=160)
    effective_date = models.DateField("Дата остатков")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state = models.CharField("Состояние", max_length=8, choices=State.choices, default=State.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "key"], name="unique_opening_key")]
        ordering = ["-effective_date", "-pk"]
        verbose_name = "Начальные остатки"
        verbose_name_plural = "Начальные остатки"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = OpeningBalance.objects.filter(pk=self.pk).values_list("state", flat=True).first()
            if previous == self.State.POSTED:
                raise ValidationError("Проведённый документ нельзя изменять.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.reference


class OpeningLine(models.Model):
    class Basis(models.TextChoices):
        WEIGHED = "WEIGHED", "Взвешено"
        COUNTED = "COUNTED", "Пересчитано"
        DECLARED = "DECLARED", "По документу"
        ESTIMATED = "ESTIMATED", "Оценка"
        RECONCILED = "RECONCILED", "Инвентаризация"

    document = models.ForeignKey(OpeningBalance, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT)
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)
    basis = models.CharField("Основание измерения", max_length=12, choices=Basis.choices)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_opening_quantity"),
            models.CheckConstraint(condition=Q(basis__in=["WEIGHED", "COUNTED", "DECLARED", "ESTIMATED", "RECONCILED"]), name="opening_basis"),
        ]
        verbose_name = "Строка начальных остатков"
        verbose_name_plural = "Строки начальных остатков"

    def clean(self):
        if not self.product_id or not self.location_id or not self.document_id:
            return
        if self.product.company_id != self.document.company_id or self.location.warehouse.company_id != self.document.company_id:
            raise ValidationError("Товар и место хранения должны относиться к этому предприятию.")
        if self.location.warehouse_id != self.document.warehouse_id:
            raise ValidationError("Место хранения не относится к выбранному складу.")
        finished = self.document.warehouse.kind == Warehouse.Kind.FINISHED
        if self.product.is_finished != finished:
            raise ValidationError("Тип товара не подходит для выбранного склада.")
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        if self.product.kind == Product.Kind.FLOUR:
            if not self.bags or self.quantity != self.product.package_kg * self.bags:
                raise ValidationError("Масса должна соответствовать количеству мешков и фасовке.")
        elif self.bags is not None:
            raise ValidationError("Количество мешков задаётся только для фасованной муки.")
        if self.product.unit == Product.Unit.PCS and self.quantity != self.quantity.to_integral_value():
            raise ValidationError("Количество штук должно быть целым.")

    def save(self, *args, **kwargs):
        if self.document_id and self.document.state == OpeningBalance.State.POSTED:
            raise ValidationError("Проведённый документ нельзя изменять.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.document.state == OpeningBalance.State.POSTED:
            raise ValidationError("Проведённый документ нельзя изменять.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.product} — {self.quantity}"


class GoodsReceipt(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Подтверждён"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT)
    order = models.ForeignKey("procurement.PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts")
    customs_acceptance = models.ForeignKey("procurement.CustomsAcceptance", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64, blank=True)
    reference = models.CharField("Основание", max_length=160)
    effective_date = models.DateField("Дата приёмки")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "key"], name="unique_receipt_key")]
        ordering = ["-effective_date", "-pk"]
        verbose_name = "Приход"
        verbose_name_plural = "Приходы"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = GoodsReceipt.objects.filter(pk=self.pk).values_list("state", flat=True).first()
            if previous == self.State.POSTED:
                raise ValidationError("Проведённый документ нельзя изменять.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.reference


class ReceiptLine(models.Model):
    document = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT)
    order_line = models.ForeignKey("procurement.OrderLine", null=True, blank=True, on_delete=models.PROTECT)
    transport_unit = models.ForeignKey("procurement.TransportUnit", null=True, blank=True, on_delete=models.PROTECT)
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)
    basis = models.CharField(max_length=12, choices=OpeningLine.Basis.choices)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_receipt_quantity")]
        verbose_name = "Строка прихода"
        verbose_name_plural = "Строки прихода"

    def clean(self):
        if not self.product_id or not self.location_id or not self.document_id:
            return
        if self.product.company_id != self.document.company_id or self.location.warehouse.company_id != self.document.company_id:
            raise ValidationError("Товар и место хранения должны относиться к этому предприятию.")
        if self.location.warehouse_id != self.document.warehouse_id or self.location.warehouse.kind != Warehouse.Kind.RAW:
            raise ValidationError("Приход записывается только на склад сырья.")
        if self.product.is_finished:
            raise ValidationError("Готовую продукцию не принимают как закупку.")
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        if self.order_line_id and (self.document.order_id != self.order_line.order_id or self.product_id != self.order_line.product_id):
            raise ValidationError("Строка заказа не относится к этому приходу.")
        if self.transport_unit_id and self.document.supplier_id != self.transport_unit.shipment.supplier_id:
            raise ValidationError("Вагон относится к другому поставщику.")
        if self.product.unit == Product.Unit.PCS and self.quantity != self.quantity.to_integral_value():
            raise ValidationError("Количество штук должно быть целым.")

    def save(self, *args, **kwargs):
        if self.document_id and self.document.state == GoodsReceipt.State.POSTED:
            raise ValidationError("Проведённый документ нельзя изменять.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product} — {self.quantity}"


class InventoryLot(models.Model):
    receipt_line = models.OneToOneField(ReceiptLine, on_delete=models.PROTECT, related_name="lot")
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    batch_reference = models.CharField("Партия поставщика", max_length=80, blank=True)

    class Meta:
        verbose_name = "Входящая партия"
        verbose_name_plural = "Входящие партии"

    def __str__(self):
        return self.batch_reference or f"Партия #{self.pk}"


class StockAdjustment(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Подтверждён"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64, blank=True)
    reason = models.CharField("Причина", max_length=200)
    effective_date = models.DateField("Дата")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "key"], name="unique_adjustment_key")]
        verbose_name = "Корректировка"
        verbose_name_plural = "Корректировки"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = StockAdjustment.objects.filter(pk=self.pk).values_list("state", flat=True).first()
            if previous == self.State.POSTED:
                raise ValidationError("Проведённый документ нельзя изменять.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.reason


class AdjustmentLine(models.Model):
    document = models.ForeignKey(StockAdjustment, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT)
    quantity = models.DecimalField("Изменение", max_digits=18, decimal_places=3)
    basis = models.CharField(max_length=12, choices=OpeningLine.Basis.choices)
    corrects = models.ForeignKey("StockLedgerEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")

    class Meta:
        constraints = [models.CheckConstraint(condition=~Q(quantity=0), name="nonzero_adjustment")]
        verbose_name = "Строка корректировки"
        verbose_name_plural = "Строки корректировки"

    def clean(self):
        if not self.product_id or not self.location_id or not self.document_id:
            return
        if self.product.company_id != self.document.company_id or self.location.warehouse_id != self.document.warehouse_id:
            raise ValidationError("Товар и место хранения должны относиться к этому документу.")
        if self.quantity == 0:
            raise ValidationError("Изменение не может быть нулевым.")
        if self.corrects_id and (self.corrects.product_id != self.product_id or self.corrects.location_id != self.location_id):
            raise ValidationError("Корректировка должна относиться к той же позиции и месту.")

    def save(self, *args, **kwargs):
        if self.document_id and self.document.state == StockAdjustment.State.POSTED:
            raise ValidationError("Проведённый документ нельзя изменять.")
        self.full_clean()
        return super().save(*args, **kwargs)


class StockPostingSource(models.Model):
    """One business line owns the ledger effects. Exactly one source line is set."""

    opening_line = models.OneToOneField(OpeningLine, null=True, blank=True, on_delete=models.PROTECT, related_name="posting_source")
    receipt_line = models.OneToOneField(ReceiptLine, null=True, blank=True, on_delete=models.PROTECT, related_name="posting_source")
    adjustment_line = models.OneToOneField(AdjustmentLine, null=True, blank=True, on_delete=models.PROTECT, related_name="posting_source")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(opening_line__isnull=False, receipt_line__isnull=True, adjustment_line__isnull=True)
                    | Q(opening_line__isnull=True, receipt_line__isnull=False, adjustment_line__isnull=True)
                    | Q(opening_line__isnull=True, receipt_line__isnull=True, adjustment_line__isnull=False)
                ),
                name="exactly_one_posting_source",
            )
        ]
        verbose_name = "Источник складской записи"
        verbose_name_plural = "Источники складских записей"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Источник проводки не изменяется.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Источник проводки не удаляется.")

    def __str__(self):
        if self.opening_line_id:
            return f"Начальные остатки #{self.opening_line_id}"
        if self.receipt_line_id:
            return f"Приход #{self.receipt_line_id}"
        return f"Корректировка #{self.adjustment_line_id}"


class StockLedgerEntry(models.Model):
    class Effect(models.TextChoices):
        OPENING = "OPENING", "Начальный остаток"
        RECEIPT = "RECEIPT", "Приход"
        ADJUSTMENT = "ADJUSTMENT", "Корректировка"

    source = models.ForeignKey(StockPostingSource, on_delete=models.PROTECT, related_name="entries")
    effect = models.CharField(max_length=12, choices=Effect.choices, default=Effect.OPENING)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="ledger_entries")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField(null=True, blank=True)
    basis = models.CharField(max_length=12)
    effective_date = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "effect"], name="unique_source_effect"),
            models.CheckConstraint(
                condition=(
                    Q(effect="OPENING", quantity__gt=0)
                    | Q(effect="RECEIPT", quantity__gt=0)
                    | Q(effect="ADJUSTMENT") & ~Q(quantity=0)
                ),
                name="ledger_effect_sign",
            ),
        ]
        indexes = [models.Index(fields=["company", "location", "product", "effective_date"])]
        verbose_name = "Складская запись"
        verbose_name_plural = "Складские записи"

    def clean(self):
        if not self.source_id or not self.product_id or not self.location_id:
            return
        if self.effect == self.Effect.OPENING:
            line = self.source.opening_line
        elif self.effect == self.Effect.RECEIPT:
            line = self.source.receipt_line
        elif self.effect == self.Effect.ADJUSTMENT:
            line = self.source.adjustment_line
        else:
            raise ValidationError("Неизвестный складской эффект.")
        if line is None or line.product_id != self.product_id or line.location_id != self.location_id:
            raise ValidationError("Складская запись не совпадает со строкой документа.")
        if line.quantity != self.quantity or line.basis != self.basis:
            raise ValidationError("Складская запись не совпадает со строкой документа.")
        if self.effect != self.Effect.ADJUSTMENT and line.bags != self.bags:
            raise ValidationError("Складская запись не совпадает со строкой документа.")
        if line.document.company_id != self.company_id or line.document.effective_date != self.effective_date:
            raise ValidationError("Складская запись не совпадает с документом.")
        if self.location.warehouse.company_id != self.company_id or self.product.company_id != self.company_id:
            raise ValidationError("Товар и место хранения должны относиться к этому предприятию.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Проведённая складская запись не изменяется.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Проведённая складская запись не удаляется.")

    def __str__(self):
        return f"{self.product} {self.quantity}"
