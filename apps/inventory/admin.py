from django.contrib import admin

from apps.inventory.models import (
    AdjustmentLine,
    GoodsReceipt,
    InventoryLot,
    OpeningBalance,
    OpeningLine,
    ReceiptLine,
    StockAdjustment,
    StockLedgerEntry,
    StockPostingSource,
    StorageLocation,
    Warehouse,
)


class InspectOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "company")
    list_filter = ("kind", "company")


@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "warehouse", "active", "is_default")
    list_filter = ("warehouse", "active")


@admin.register(OpeningBalance)
class OpeningBalanceAdmin(InspectOnlyAdmin):
    list_display = ("reference", "company", "warehouse", "effective_date", "state", "actor")
    list_filter = ("state", "company")


@admin.register(OpeningLine)
class OpeningLineAdmin(InspectOnlyAdmin):
    list_display = ("document", "product", "location", "quantity", "bags", "basis")


@admin.register(StockPostingSource)
class StockPostingSourceAdmin(InspectOnlyAdmin):
    list_display = ("opening_line",)


@admin.register(StockLedgerEntry)
class StockLedgerEntryAdmin(InspectOnlyAdmin):
    list_display = ("effective_date", "company", "product", "location", "effect", "quantity", "bags")
    list_filter = ("effect", "company")


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(InspectOnlyAdmin):
    list_display = ("reference", "company", "supplier", "effective_date", "state")


@admin.register(ReceiptLine)
class ReceiptLineAdmin(InspectOnlyAdmin):
    list_display = ("document", "product", "location", "quantity")


@admin.register(InventoryLot)
class InventoryLotAdmin(InspectOnlyAdmin):
    list_display = ("product", "batch_reference")


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(InspectOnlyAdmin):
    list_display = ("reason", "company", "effective_date", "state")


@admin.register(AdjustmentLine)
class AdjustmentLineAdmin(InspectOnlyAdmin):
    list_display = ("document", "product", "location", "quantity")
