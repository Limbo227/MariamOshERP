from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Company


class SupplierQualityValue(models.Model):
    shipment = models.ForeignKey("procurement.Shipment", on_delete=models.PROTECT, related_name="passport_values")
    transport_unit = models.ForeignKey("procurement.TransportUnit", null=True, blank=True, on_delete=models.PROTECT)
    parameter = models.CharField("Показатель", max_length=80)
    number = models.DecimalField("Число", max_digits=12, decimal_places=3, null=True, blank=True)
    text = models.CharField("Текст", max_length=80, blank=True)
    unit = models.CharField("Единица", max_length=20, blank=True)
    passport_version = models.CharField("Паспорт", max_length=40, blank=True)

    class Meta:
        verbose_name = "Значение паспорта"
        verbose_name_plural = "Значения паспорта"

    def clean(self):
        if self.transport_unit_id and self.transport_unit.shipment_id != self.shipment_id:
            raise ValidationError("Вагон относится к другой поставке.")
        if self.number is None and not self.text:
            raise ValidationError("Нужно число или текст.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class QualityInspection(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    transport_unit = models.ForeignKey("procurement.TransportUnit", null=True, blank=True, on_delete=models.PROTECT)
    receipt_line = models.ForeignKey("inventory.ReceiptLine", null=True, blank=True, on_delete=models.PROTECT)
    inspected_on = models.DateField("Дата")
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    comment = models.CharField("Комментарий", max_length=200, blank=True)

    class Meta:
        verbose_name = "Местная проверка"
        verbose_name_plural = "Местные проверки"

    def clean(self):
        if not self.transport_unit_id and not self.receipt_line_id:
            raise ValidationError("Проверка относится к вагону или к строке прихода.")
        if self.transport_unit_id and self.receipt_line_id and self.receipt_line.transport_unit_id not in (None, self.transport_unit_id):
            raise ValidationError("Вагон и строка прихода не совпадают.")
        if self.receipt_line_id and self.receipt_line.document.company_id != self.company_id:
            raise ValidationError("Проверка относится к другому предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LocalQualityValue(models.Model):
    inspection = models.ForeignKey(QualityInspection, on_delete=models.PROTECT, related_name="values")
    parameter = models.CharField("Показатель", max_length=80)
    number = models.DecimalField("Число", max_digits=12, decimal_places=3, null=True, blank=True)
    text = models.CharField("Текст", max_length=80, blank=True)
    unit = models.CharField("Единица", max_length=20, blank=True)

    class Meta:
        verbose_name = "Местное значение"
        verbose_name_plural = "Местные значения"

    def clean(self):
        if self.number is None and not self.text:
            raise ValidationError("Нужно число или текст.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ReleaseDecision(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Действует"
        REVOKED = "REVOKED", "Отменено"

    receipt_line = models.ForeignKey("inventory.ReceiptLine", on_delete=models.PROTECT, related_name="releases")
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    reason = models.CharField("Основание", max_length=200)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    key = models.UUIDField()
    released_on = models.DateField("Дата")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key"], name="unique_release_key"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="positive_release"),
        ]
        verbose_name = "Допуск в производство"
        verbose_name_plural = "Допуски в производство"

    def __str__(self):
        return f"{self.quantity} / {self.receipt_line_id}"


class ExceptionRecord(models.Model):
    class State(models.TextChoices):
        OPEN = "OPEN", "Открыто"
        RESOLVED = "RESOLVED", "Разобрано"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    order = models.ForeignKey("procurement.PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT)
    receipt = models.ForeignKey("inventory.GoodsReceipt", null=True, blank=True, on_delete=models.PROTECT)
    summary = models.TextField("Расхождение")
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Расхождение"
        verbose_name_plural = "Расхождения"
