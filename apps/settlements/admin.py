from django.contrib import admin

from apps.settlements.models import (
    ObligationEntry,
    PaymentAllocation,
    SupplierObligation,
    SupplierPayment,
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


@admin.register(SupplierObligation)
class SupplierObligationAdmin(InspectOnlyAdmin):
    list_display = ("company", "supplier", "order", "manual_reference")


@admin.register(ObligationEntry)
class ObligationEntryAdmin(InspectOnlyAdmin):
    list_display = ("obligation", "kind", "amount", "effective_date")


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(InspectOnlyAdmin):
    list_display = ("external_reference", "supplier", "amount", "paid_on")


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(InspectOnlyAdmin):
    list_display = ("payment", "obligation", "amount")
