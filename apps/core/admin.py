from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.core.models import Document, Organization, Party, User


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class CoreUserAdmin(UserAdmin):
    pass


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "currency", "timezone")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "is_supplier", "is_customer", "active")
    list_filter = ("is_supplier", "is_customer", "active")
    search_fields = ("name",)


@admin.register(Document)
class DocumentAdmin(ReadOnlyAdmin):
    list_display = ("number", "kind", "state", "effective_date", "posted_at")
    list_filter = ("kind", "state")
    search_fields = ("number",)
