from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.core.models import AuditEvent, Company, Membership, OperationKey, User, WarehouseGrant


class InspectOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(User)
class CoreUserAdmin(UserAdmin):
    pass


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "timezone")
    search_fields = ("name", "code")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "role")
    list_filter = ("company",)


@admin.register(WarehouseGrant)
class WarehouseGrantAdmin(admin.ModelAdmin):
    list_display = ("membership", "warehouse")


@admin.register(AuditEvent)
class AuditEventAdmin(InspectOnlyAdmin):
    list_display = ("recorded_at", "company", "actor", "action", "object_label")
    list_filter = ("action", "company")


@admin.register(OperationKey)
class OperationKeyAdmin(InspectOnlyAdmin):
    list_display = ("created_at", "company", "command", "result_label", "actor")
    list_filter = ("command",)
