from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Company


class Product(models.Model):
    class Kind(models.TextChoices):
        WHEAT = "WHEAT", "Пшеница"
        SACK = "SACK", "Пустой мешок"
        MATERIAL = "MATERIAL", "Другой материал"
        FLOUR = "FLOUR", "Мука в мешках"
        BYPRODUCT = "BYPRODUCT", "Побочный продукт"

    class Unit(models.TextChoices):
        KG = "KG", "кг"
        PCS = "PCS", "шт."

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku = models.CharField("Код", max_length=40)
    name = models.CharField("Название", max_length=160)
    kind = models.CharField("Тип", max_length=12, choices=Kind.choices)
    unit = models.CharField("Единица учёта", max_length=3, choices=Unit.choices, default=Unit.KG)
    package_kg = models.DecimalField("Масса мешка, кг", max_digits=10, decimal_places=3, null=True, blank=True)
    active = models.BooleanField("Активен", default=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "sku"], name="unique_company_sku"),
            models.CheckConstraint(condition=Q(kind__in=["WHEAT", "SACK", "MATERIAL", "FLOUR", "BYPRODUCT"]), name="product_valid_kind"),
            models.CheckConstraint(condition=Q(unit__in=["KG", "PCS"]), name="product_valid_unit"),
            models.CheckConstraint(condition=(Q(kind="FLOUR", package_kg__gt=0, package_kg__isnull=False, unit="KG") | (~Q(kind="FLOUR") & Q(package_kg__isnull=True))), name="valid_package_mass"),
            models.CheckConstraint(condition=(~Q(kind__in=["WHEAT", "BYPRODUCT"]) | Q(unit="KG")), name="mass_product_in_kg"),
            models.CheckConstraint(condition=(~Q(kind="SACK") | Q(unit="PCS")), name="sack_in_pieces"),
        ]
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    @property
    def is_finished(self):
        return self.kind in (self.Kind.FLOUR, self.Kind.BYPRODUCT)

    def clean(self):
        if self.pk and self.stockentry_set.exists():
            old = Product.objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in ("company_id", "kind", "unit", "package_kg")):
                raise ValidationError("У товара с движениями нельзя менять тип, единицу или фасовку.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductRequirement(models.Model):
    product = models.OneToOneField(Product, on_delete=models.PROTECT, related_name="requirement", verbose_name="Готовый товар")
    component = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="used_by", verbose_name="Пустой мешок")
    quantity = models.PositiveSmallIntegerField("На единицу выпуска", default=1, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity=1), name="one_sack_per_bag")]
        verbose_name = "Материал для выпуска"
        verbose_name_plural = "Материалы для выпуска"

    def clean(self):
        if not self.product_id or not self.component_id:
            return
        if self.product.company_id != self.component.company_id:
            raise ValidationError("Товары должны относиться к одному предприятию.")
        if self.product.kind != Product.Kind.FLOUR or self.component.kind != Product.Kind.SACK:
            raise ValidationError("Для муки в мешках требуется один пустой мешок.")
        if self.quantity != Decimal("1"):
            raise ValidationError("Для одного готового мешка нужен один пустой мешок.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Supplier(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField("Название", max_length=160)
    reference = models.CharField("Код", max_length=40)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "reference"], name="unique_supplier_reference")]
        ordering = ["name"]
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"

    def __str__(self):
        return self.name

