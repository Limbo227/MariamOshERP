from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Company


class SupplierObligation(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT)
    currency = models.CharField(max_length=3, default="KGS")
    order = models.OneToOneField("procurement.PurchaseOrder", null=True, blank=True, on_delete=models.PROTECT)
    manual_reference = models.CharField("Основание", max_length=160, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(currency="KGS"), name="obligation_currency_kgs"),
            models.CheckConstraint(
                condition=(Q(order__isnull=False, manual_reference="") | Q(order__isnull=True) & ~Q(manual_reference="")),
                name="obligation_one_source",
            ),
        ]
        verbose_name = "Долг поставщику"
        verbose_name_plural = "Долги поставщикам"

    def __str__(self):
        return self.manual_reference or str(self.order)


class ObligationEntry(models.Model):
    class Kind(models.TextChoices):
        INITIAL = "INITIAL", "Первоначальный долг"
        AMENDMENT = "AMENDMENT", "Изменение"
        MANUAL = "MANUAL", "Отдельное основание"

    obligation = models.ForeignKey(SupplierObligation, on_delete=models.PROTECT, related_name="entries")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    source_key = models.CharField(max_length=64)
    effective_date = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["obligation", "source_key"], name="unique_obligation_source"),
            models.CheckConstraint(condition=~Q(amount=0), name="nonzero_obligation_entry"),
        ]
        verbose_name = "Проводка долга"
        verbose_name_plural = "Проводки долга"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Проведённая сумма долга не изменяется.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Проведённая сумма долга не удаляется.")


class SupplierPayment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Касса"
        BANK = "BANK", "Банк"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey("catalog.Supplier", on_delete=models.PROTECT)
    currency = models.CharField(max_length=3, default="KGS")
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)
    paid_on = models.DateField("Дата")
    external_reference = models.CharField("Внешняя ссылка", max_length=80)
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.BANK)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="unique_payment_key"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="positive_supplier_payment"),
            models.CheckConstraint(condition=Q(currency="KGS"), name="payment_currency_kgs"),
        ]
        verbose_name = "Оплата поставщику"
        verbose_name_plural = "Оплаты поставщикам"

    def __str__(self):
        return self.external_reference


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(SupplierPayment, on_delete=models.PROTECT, related_name="allocations")
    obligation = models.ForeignKey(SupplierObligation, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    allocated_on = models.DateField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="positive_allocation")]
        verbose_name = "Зачёт оплаты"
        verbose_name_plural = "Зачёты оплаты"

    def clean(self):
        if self.payment_id and self.obligation_id:
            same = (
                self.payment.company_id == self.obligation.company_id
                and self.payment.supplier_id == self.obligation.supplier_id
                and self.payment.currency == self.obligation.currency
            )
            if not same:
                raise ValidationError("Оплата и долг должны совпадать по предприятию, поставщику и валюте.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Зачёт оплаты не изменяется.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Зачёт оплаты не удаляется.")
