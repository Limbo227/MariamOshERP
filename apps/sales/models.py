from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import FrozenLine
from apps.core.quantities import line_amount


class Sale(models.Model):
    document = models.OneToOneField("core.Document", on_delete=models.PROTECT, related_name="sale")
    customer = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="sales")

    class Meta:
        db_table = "sale"
        verbose_name = "Продажа"
        verbose_name_plural = "Продажи"

    def clean(self):
        if self.customer_id and not self.customer.is_customer:
            raise ValidationError("Продажа оформляется на покупателя.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Продажа не изменяется.")
        if self.document.state != self.document.State.DRAFT:
            raise ValidationError("Продажа создаётся до проведения.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.document)


class SaleLine(FrozenLine):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    price = models.DecimalField("Цена", max_digits=18, decimal_places=4)
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)

    class Meta:
        db_table = "sale_line"
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="sale_qty"),
            models.CheckConstraint(condition=Q(price__gt=0), name="sale_price"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="sale_amount"),
        ]
        verbose_name = "Строка продажи"
        verbose_name_plural = "Строки продажи"

    def document_for_edit(self):
        return self.sale.document

    def clean(self):
        from apps.inventory.checks import ensure_packaging

        ensure_packaging(self.product, self.quantity, self.bags)
        if self.quantity and self.price and self.amount != line_amount(self.quantity, self.price):
            raise ValidationError("Сумма строки должна равняться количеству, умноженному на цену.")
