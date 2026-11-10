from django.contrib import admin

from apps.catalog.models import OriginStation, Product, ProductRequirement, Supplier


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "kind", "unit", "grade", "package_kg", "company", "active")
    list_filter = ("kind", "company", "active")
    search_fields = ("sku", "name")


@admin.register(ProductRequirement)
class ProductRequirementAdmin(admin.ModelAdmin):
    list_display = ("product", "component", "quantity")


@admin.register(OriginStation)
class OriginStationAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "active")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "reference", "is_supplier", "is_customer", "is_other", "company", "active")
    list_filter = ("company", "active")
    search_fields = ("name", "reference")
