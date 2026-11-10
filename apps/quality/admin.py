from django.contrib import admin

from apps.quality.models import (
    ExceptionRecord,
    QualityInspection,
    ReleaseDecision,
    SupplierQualityValue,
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


@admin.register(SupplierQualityValue)
class SupplierQualityValueAdmin(InspectOnlyAdmin):
    list_display = ("shipment", "parameter", "number", "unit")


@admin.register(QualityInspection)
class QualityInspectionAdmin(InspectOnlyAdmin):
    list_display = ("company", "inspected_on", "inspector")


@admin.register(ReleaseDecision)
class ReleaseDecisionAdmin(InspectOnlyAdmin):
    list_display = ("receipt_line", "quantity", "status", "released_on")


@admin.register(ExceptionRecord)
class ExceptionRecordAdmin(InspectOnlyAdmin):
    list_display = ("company", "state", "summary")
