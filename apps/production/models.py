from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import FrozenLine


class ProductionReport(models.Model):
    document = models.OneToOneField("core.Document", on_delete=models.PROTECT, related_name="production")

    class Meta:
        db_table = "production_report"
        verbose_name = "Выпуск"
        verbose_name_plural = "Выпуски"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Выпуск не изменяется.")
        if self.document.state != self.document.State.DRAFT:
            raise ValidationError("Выпуск создаётся до проведения.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.document)


class OutputLine(FrozenLine):
    report = models.ForeignKey(ProductionReport, on_delete=models.PROTECT, related_name="outputs")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="output_lines")
    location = models.ForeignKey("inventory.StorageLocation", on_delete=models.PROTECT, related_name="output_lines")
    packaging_location = models.ForeignKey(
        "inventory.StorageLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="packaging_outputs"
    )
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)

    class Meta:
        db_table = "output_line"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="output_qty")]
        verbose_name = "Строка выпуска"
        verbose_name_plural = "Строки выпуска"

    def document_for_edit(self):
        return self.report.document

    def clean(self):
        from apps.inventory.checks import ensure_location, ensure_packaging, sack_pieces

        ensure_packaging(self.product, self.quantity, self.bags)
        ensure_location(self.product, self.location)
        if not self.product_id:
            return
        pieces = sack_pieces(self.product, self.quantity, self.bags)
        if pieces and not self.packaging_location_id:
            raise ValidationError("Укажите, откуда списать пустые мешки.")
        if self.packaging_location_id and not pieces:
            raise ValidationError("Место мешков указывается, когда для муки задан пустой мешок.")
        if self.packaging_location_id:
            ensure_location(self.product.sack, self.packaging_location)


class InputLine(FrozenLine):
    report = models.ForeignKey(ProductionReport, on_delete=models.PROTECT, related_name="inputs")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="input_lines")
    location = models.ForeignKey("inventory.StorageLocation", on_delete=models.PROTECT, related_name="input_lines")
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)

    class Meta:
        db_table = "input_line"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="input_qty")]
        verbose_name = "Строка расхода"
        verbose_name_plural = "Строки расхода"

    def document_for_edit(self):
        return self.report.document

    def clean(self):
        from apps.inventory.checks import ensure_location

        ensure_location(self.product, self.location)
