from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import FrozenLine, LedgerRow

DEFAULT_LOCATION_NAME = "Основное"


class ProductCategory(models.Model):
    """User-managed product type. `role` keeps the technical inventory rules."""

    class Role(models.TextChoices):
        WHEAT = "WHEAT", "Пшеница"
        SACK = "SACK", "Пустой мешок"
        MATERIAL = "MATERIAL", "Материал"
        FLOUR = "FLOUR", "Мука"
        BYPRODUCT = "BYPRODUCT", "Побочный продукт"
        OTHER = "OTHER", "Прочее"

    name = models.CharField("Название", max_length=80)
    code = models.CharField("Код", max_length=40, unique=True)
    active = models.BooleanField("Активна", default=True)
    description = models.TextField("Описание", blank=True)
    role = models.CharField("Техническая роль", max_length=12, choices=Role.choices, default=Role.OTHER)

    class Meta:
        db_table = "product_category"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=["WHEAT", "SACK", "MATERIAL", "FLOUR", "BYPRODUCT", "OTHER"]),
                name="category_role",
            ),
        ]
        verbose_name = "Категория товара"
        verbose_name_plural = "Категории товаров"

    def __str__(self):
        return self.name


class UnitOfMeasure(models.Model):
    code = models.CharField("Код", max_length=8, unique=True)
    name = models.CharField("Название", max_length=40)
    active = models.BooleanField("Активна", default=True)

    class Meta:
        db_table = "unit_of_measure"
        ordering = ["code"]
        verbose_name = "Единица измерения"
        verbose_name_plural = "Единицы измерения"

    def __str__(self):
        return self.name


class Product(models.Model):
    class Kind(models.TextChoices):
        WHEAT = "WHEAT", "Пшеница"
        SACK = "SACK", "Пустой мешок"
        MATERIAL = "MATERIAL", "Материал"
        FLOUR = "FLOUR", "Мука в мешках"
        BYPRODUCT = "BYPRODUCT", "Побочный продукт"
        OTHER = "OTHER", "Прочее"

    class Unit(models.TextChoices):
        PCS = "PCS", "шт"
        KG = "KG", "кг"
        L = "L", "литр"
        BAG = "BAG", "мш"

    sku = models.CharField("Код", max_length=40, unique=True)
    name = models.CharField("Название", max_length=160)
    category = models.ForeignKey(
        ProductCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Категория",
    )
    kind = models.CharField("Тип", max_length=12, choices=Kind.choices)
    unit = models.CharField("Единица", max_length=8, choices=Unit.choices, default=Unit.KG)
    unit_weight_kg = models.DecimalField(
        "Масса одной единицы, кг", max_digits=12, decimal_places=3, null=True, blank=True
    )
    package_kg = models.DecimalField("Масса мешка, кг", max_digits=10, decimal_places=3, null=True, blank=True)
    sack = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="packed_products", verbose_name="Пустой мешок"
    )
    active = models.BooleanField("Активен", default=True)

    class Meta:
        db_table = "product"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["WHEAT", "SACK", "MATERIAL", "FLOUR", "BYPRODUCT", "OTHER"]),
                name="product_kind",
            ),
            models.CheckConstraint(condition=Q(unit__in=["PCS", "KG", "L", "BAG"]), name="product_unit"),
            models.CheckConstraint(
                condition=(
                    Q(kind="FLOUR", unit="KG", package_kg__gt=0)
                    | Q(kind="FLOUR", unit="BAG", package_kg__isnull=True, unit_weight_kg__gt=0)
                    | (~Q(kind="FLOUR") & Q(package_kg__isnull=True))
                ),
                name="product_package",
            ),
            models.CheckConstraint(
                condition=(~Q(kind__in=["WHEAT", "BYPRODUCT"]) | Q(unit="KG")),
                name="mass_in_kg",
            ),
            models.CheckConstraint(
                condition=(~Q(kind="FLOUR") | Q(unit__in=["KG", "BAG"])),
                name="flour_unit",
            ),
            models.CheckConstraint(condition=(~Q(kind="SACK") | Q(unit="PCS")), name="sack_in_pieces"),
            models.CheckConstraint(
                condition=Q(unit="KG", unit_weight_kg=1) | ~Q(unit="KG"),
                name="kg_weight_is_one",
            ),
            models.CheckConstraint(
                condition=Q(unit="BAG", unit_weight_kg__gt=0) | ~Q(unit="BAG"),
                name="bag_weight_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_weight_kg__isnull=True) | Q(unit_weight_kg__gt=0),
                name="unit_weight_positive",
            ),
        ]
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    def clean(self):
        self._prepare_identity()
        if self.category_id is None:
            raise ValidationError("Укажите категорию товара.")
        if not UnitOfMeasure.objects.filter(code=self.unit, active=True).exists():
            raise ValidationError("Неизвестная единица измерения.")
        if self.sack_id and self.pk and self.sack_id == self.pk:
            raise ValidationError("Товар не может быть собственной упаковкой.")
        if self.sack_id and self.sack.kind != self.Kind.SACK:
            raise ValidationError("В качестве упаковки нужен пустой мешок.")
        if self.kind != self.Kind.FLOUR and self.sack_id:
            raise ValidationError("Пустой мешок задаётся для фасованной муки.")
        if self.unit == self.Unit.KG and self.unit_weight_kg != Decimal("1"):
            raise ValidationError("Для килограмма масса одной единицы всегда равна 1.")
        if self.unit == self.Unit.BAG and (self.unit_weight_kg is None or self.unit_weight_kg <= 0):
            raise ValidationError("Для товара в мешках укажите массу одного мешка, кг.")
        if self.unit_weight_kg is not None and self.unit_weight_kg <= 0:
            raise ValidationError("Масса единицы должна быть больше нуля.")
        if self.pk and self.stock_moves.exists():
            previous = Product.objects.get(pk=self.pk)
            locked = ("kind", "unit", "package_kg", "sack_id", "unit_weight_kg")
            if any(getattr(previous, field) != getattr(self, field) for field in locked):
                raise ValidationError(
                    "У товара с движениями нельзя менять тип, единицу, массу единицы, фасовку или мешок."
                )

    def _prepare_identity(self):
        if self.category_id:
            self.kind = self.category.role
        elif self.kind:
            category = ProductCategory.objects.filter(code=self.kind).first()
            if category is None:
                category = ProductCategory.objects.filter(role=self.kind, active=True).order_by("pk").first()
            if category is None:
                raise ValidationError("Для типа товара нет категории. Сначала заполните справочник категорий.")
            self.category = category
        if self.unit == self.Unit.KG:
            self.unit_weight_kg = Decimal("1.000")
        elif self.unit == self.Unit.BAG and self.kind == self.Kind.FLOUR:
            self.package_kg = None
        elif self.unit != self.Unit.KG and self.kind != self.Kind.FLOUR:
            self.package_kg = None

    def save(self, *args, **kwargs):
        self._prepare_identity()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    class Kind(models.TextChoices):
        RAW = "RAW", "Сырьё"
        FINISHED = "FINISHED", "Готовая продукция"

    code = models.SlugField("Код", unique=True)
    name = models.CharField("Название", max_length=80)
    kind = models.CharField("Тип", max_length=8, choices=Kind.choices)
    active = models.BooleanField("Активен", default=True)

    class Meta:
        db_table = "warehouse"
        ordering = ["name"]
        constraints = [models.CheckConstraint(condition=Q(kind__in=["RAW", "FINISHED"]), name="warehouse_kind")]
        verbose_name = "Склад"
        verbose_name_plural = "Склады"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from apps.inventory.services import ensure_default_location

        ensure_default_location(self)

    def __str__(self):
        return self.name


class StorageLocation(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="locations")
    name = models.CharField("Название", max_length=80)
    active = models.BooleanField("Активно", default=True)

    class Meta:
        db_table = "storage_location"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["warehouse", "name"], name="location_name")]
        verbose_name = "Место хранения"
        verbose_name_plural = "Места хранения"

    def __str__(self):
        return f"{self.warehouse}: {self.name}"


class StockPosition(models.Model):
    """Stable lock row for a product at a place. The quantity lives on StockMove."""

    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name="positions")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="positions")

    class Meta:
        db_table = "stock_position"
        constraints = [models.UniqueConstraint(fields=["location", "product"], name="stock_position_unique")]
        verbose_name = "Складская позиция"
        verbose_name_plural = "Складские позиции"

    def __str__(self):
        return f"{self.product} @ {self.location}"


class GoodsReceipt(models.Model):
    document = models.OneToOneField("core.Document", on_delete=models.PROTECT, related_name="receipt")
    supplier = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="receipts")

    class Meta:
        db_table = "goods_receipt"
        verbose_name = "Приёмка"
        verbose_name_plural = "Приёмки"

    def clean(self):
        if self.supplier_id and not self.supplier.is_supplier:
            raise ValidationError("Приёмка оформляется на поставщика.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Приёмка не изменяется.")
        if self.document.state != self.document.State.DRAFT:
            raise ValidationError("Приёмка создаётся до проведения.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.document)


class ReceiptLine(FrozenLine):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="receipt_lines")
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name="receipt_lines")
    purchase_line = models.ForeignKey(
        "procurement.PurchaseLine", null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)

    class Meta:
        db_table = "receipt_line"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="receipt_qty")]
        verbose_name = "Строка приёмки"
        verbose_name_plural = "Строки приёмки"

    def document_for_edit(self):
        return self.receipt.document

    def clean(self):
        from apps.inventory.checks import ensure_location, ensure_packaging

        ensure_packaging(self.product, self.quantity, self.bags)
        ensure_location(self.product, self.location)
        if self.location_id and self.receipt_id and self.location.warehouse_id != self.receipt.warehouse_id:
            raise ValidationError("Место хранения не относится к складу приёмки.")
        if self.purchase_line_id:
            if self.product_id != self.purchase_line.product_id:
                raise ValidationError("В приёмке и в закупке должен быть один товар.")
            if self.receipt.supplier_id != self.purchase_line.order.supplier_id:
                raise ValidationError("Поставщик приёмки и закупки должен совпадать.")


class GoodsIssue(models.Model):
    document = models.OneToOneField("core.Document", on_delete=models.PROTECT, related_name="issue")
    customer = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="issues")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="issues")

    class Meta:
        db_table = "goods_issue"
        verbose_name = "Выдача"
        verbose_name_plural = "Выдачи"

    def clean(self):
        if self.customer_id and not self.customer.is_customer:
            raise ValidationError("Выдача оформляется на покупателя.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Выдача не изменяется.")
        if self.document.state != self.document.State.DRAFT:
            raise ValidationError("Выдача создаётся до проведения.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.document)


class IssueLine(FrozenLine):
    issue = models.ForeignKey(GoodsIssue, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="issue_lines")
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name="issue_lines")
    sale_line = models.ForeignKey(
        "sales.SaleLine", null=True, blank=True, on_delete=models.PROTECT, related_name="issues"
    )
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)

    class Meta:
        db_table = "issue_line"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="issue_qty")]
        verbose_name = "Строка выдачи"
        verbose_name_plural = "Строки выдачи"

    def document_for_edit(self):
        return self.issue.document

    def clean(self):
        from apps.inventory.checks import ensure_location, ensure_packaging

        ensure_packaging(self.product, self.quantity, self.bags)
        ensure_location(self.product, self.location)
        if self.location_id and self.issue_id and self.location.warehouse_id != self.issue.warehouse_id:
            raise ValidationError("Место хранения не относится к складу выдачи.")
        if self.sale_line_id:
            if self.product_id != self.sale_line.product_id:
                raise ValidationError("В выдаче и в продаже должен быть один товар.")
            if self.issue.customer_id != self.sale_line.sale.customer_id:
                raise ValidationError("Покупатель выдачи и продажи должен совпадать.")


class OpeningStockLine(FrozenLine):
    opening = models.ForeignKey("core.OpeningBalance", on_delete=models.PROTECT, related_name="stock_lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="opening_stock")
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name="opening_stock")
    quantity = models.DecimalField("Количество", max_digits=18, decimal_places=3)
    bags = models.PositiveIntegerField("Мешки", null=True, blank=True)

    class Meta:
        db_table = "opening_stock_line"
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="opening_stock_qty")]
        verbose_name = "Начальный остаток товара"
        verbose_name_plural = "Начальные остатки товара"

    def document_for_edit(self):
        return self.opening.document

    def clean(self):
        from apps.inventory.checks import ensure_location, ensure_packaging

        ensure_packaging(self.product, self.quantity, self.bags)
        ensure_location(self.product, self.location)


class StockMove(LedgerRow):
    document = models.ForeignKey("core.Document", on_delete=models.PROTECT, related_name="stock_moves")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_moves")
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name="stock_moves")
    qty_delta = models.DecimalField(max_digits=18, decimal_places=3)
    bags_delta = models.IntegerField(null=True, blank=True)
    unit_code = models.CharField(max_length=8, blank=True)
    unit_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_move"
        constraints = [
            models.CheckConstraint(condition=~Q(qty_delta=0), name="stock_qty_nonzero"),
            models.CheckConstraint(
                condition=(
                    Q(bags_delta__isnull=True)
                    | Q(bags_delta__gt=0, qty_delta__gt=0)
                    | Q(bags_delta__lt=0, qty_delta__lt=0)
                ),
                name="stock_bag_sign",
            ),
        ]
        indexes = [models.Index(fields=["location", "product", "effective_date"], name="stock_position_date")]
        verbose_name = "Движение товара"
        verbose_name_plural = "Движения товара"

    def clean(self):
        if self.bags_delta is not None and self.qty_delta and (self.bags_delta > 0) != (self.qty_delta > 0):
            raise ValidationError("Знак мешков и массы должен совпадать.")
