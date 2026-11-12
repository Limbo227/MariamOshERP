from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.finance.models import (
    Allocation,
    CashOperation,
    ExpenseCategory,
    MoneyAccount,
    MoneyDocument,
    MoneyMove,
    OpenItem,
)


@admin.register(MoneyAccount)
class MoneyAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "currency", "overdraft_limit", "active")


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "active")
    search_fields = ("name", "code")


@admin.register(CashOperation)
class CashOperationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "effect", "category", "source_kind", "destination_kind", "active")
    list_filter = ("effect", "category", "active")
    search_fields = ("name", "code")


@admin.register(MoneyDocument)
class MoneyDocumentAdmin(ReadOnlyAdmin):
    list_display = (
        "document",
        "operation",
        "account",
        "amount",
        "counter_account",
        "destination_amount",
        "rate_display",
    )


@admin.register(MoneyMove)
class MoneyMoveAdmin(ReadOnlyAdmin):
    list_display = ("effective_date", "account", "amount_delta", "operation", "document")


@admin.register(OpenItem)
class OpenItemAdmin(ReadOnlyAdmin):
    list_display = ("effective_date", "party", "lane", "side", "amount", "order", "document")


@admin.register(Allocation)
class AllocationAdmin(ReadOnlyAdmin):
    list_display = ("effective_date", "amount", "we_owe", "they_owe", "document")
