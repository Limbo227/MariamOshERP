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

    def __str__(self):
        return self.name


class StorageLocation(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    name = models.CharField(max_length=80, default="Основное хранение")
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "name"], name="unique_location_name"),
            models.UniqueConstraint(fields=["warehouse"], condition=Q(is_default=True), name="one_default_location"),
        ]


class OpeningBalance(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Подтверждён"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    reference = models.CharField("Основание", max_length=160)
    effective_date = models.DateField("Дата остатков")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "key"], name="unique_opening_key")]


class OpeningLine(models.Model):
    document = models.ForeignKey(OpeningBalance, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField(null=True)
    basis = models.CharField(max_length=12, choices=[("WEIGHED", "Взвешено"), ("COUNTED", "Пересчитано"), ("DECLARED", "По документу"), ("ESTIMATED", "Оценка"), ("RECONCILED", "Инвентаризация")])

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_opening_quantity")]

    def clean(self):
        if self.product.company_id != self.document.company_id or self.location.warehouse_id != self.document.warehouse_id:
            raise ValidationError("Товар и место хранения должны соответствовать документу.")
        finished = self.document.warehouse.kind == Warehouse.Kind.FINISHED
        if self.product.is_finished != finished:
            raise ValidationError("Тип товара не подходит для выбранного склада.")
        if self.product.kind == Product.Kind.FLOUR:
            if not self.bags or self.quantity != self.product.package_kg * self.bags:
                raise ValidationError("Масса должна соответствовать количеству мешков и фасовке.")
        elif self.bags is not None:
            raise ValidationError("Количество мешков задаётся только для фасованной муки.")
        if self.product.unit == Product.Unit.PCS and self.quantity != self.quantity.to_integral_value():
            raise ValidationError("Количество штук должно быть целым.")


class StockEntry(models.Model):
    source = models.OneToOneField(OpeningLine, on_delete=models.PROTECT)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField(null=True)
    basis = models.CharField(max_length=12)
    effective_date = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_opening_entry")]
        indexes = [models.Index(fields=["company", "location", "product", "effective_date"])]

