from django.contrib import admin

from apps.catalog.models import Product, ProductRequirement, Supplier


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "kind", "unit", "grade", "package_kg", "company", "active")
    list_filter = ("kind", "company", "active")
    search_fields = ("sku", "name")


@admin.register(ProductRequirement)
class ProductRequirementAdmin(admin.ModelAdmin):
    list_display = ("product", "component", "quantity")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "reference", "company", "active")
    list_filter = ("company", "active")
    search_fields = ("name", "reference")
