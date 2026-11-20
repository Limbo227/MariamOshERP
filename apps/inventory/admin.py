from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.inventory.models import (
    Product,
    ProductCategory,
    StockMove,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "active")
    list_filter = ("active",)
    search_fields = ("name", "code")


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "active")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "unit", "unit_weight_kg", "package_kg", "active")
    list_filter = ("category", "unit", "active")
    search_fields = ("sku", "name")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "category", "active")


@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "warehouse", "active")
    list_filter = ("warehouse",)


@admin.register(StockMove)
class StockMoveAdmin(ReadOnlyAdmin):
    list_display = ("effective_date", "product", "location", "qty_delta", "bags_delta", "document")
