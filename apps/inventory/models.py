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


class StockPostingSource(models.Model):
    """The business line that owns one or more ledger effects.

    Phase 1 records an opening line only. Later phases add receipt, output,
    issue and adjustment lines, with a check that exactly one of them is set.
    """

    opening_line = models.OneToOneField(OpeningLine, on_delete=models.PROTECT, related_name="posting_source")

    class Meta:
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
        return f"Начальные остатки #{self.opening_line_id}"


class StockLedgerEntry(models.Model):
    class Effect(models.TextChoices):
        OPENING = "OPENING", "Начальный остаток"

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
            models.CheckConstraint(condition=Q(effect="OPENING"), name="phase1_opening_effect_only"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="opening_effect_positive"),
        ]
        indexes = [models.Index(fields=["company", "location", "product", "effective_date"])]
        verbose_name = "Складская запись"
        verbose_name_plural = "Складские записи"

    def clean(self):
        if not self.source_id or not self.product_id or not self.location_id:
            return
        line = self.source.opening_line
        if line.product_id != self.product_id or line.location_id != self.location_id:
            raise ValidationError("Складская запись не совпадает со строкой документа.")
        if line.quantity != self.quantity or line.bags != self.bags or line.basis != self.basis:
            raise ValidationError("Складская запись не совпадает со строкой документа.")
        if line.document.company_id != self.company_id or line.document.effective_date != self.effective_date:
            raise ValidationError("Складская запись не совпадает с документом.")
        if self.location.warehouse.company_id != self.company_id or self.product.company_id != self.company_id:
            raise ValidationError("Товар и место хранения должны относиться к этому предприятию.")
        if self.effect != self.Effect.OPENING:
            raise ValidationError("На этом этапе проводится только начальный остаток.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Проведённая складская запись не изменяется.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Проведённая складская запись не удаляется.")

    def __str__(self):
        return f"{self.product} {self.quantity}"
