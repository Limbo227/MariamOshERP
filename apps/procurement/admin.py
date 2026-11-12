from django.contrib import admin

from apps.procurement.models import (
    DeliveryTerm,
    PurchaseContract,
    RailwayStation,
    Shipment,
    ShipmentWagon,
)


@admin.register(DeliveryTerm)
class DeliveryTermAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "active")
    search_fields = ("name", "code")


@admin.register(RailwayStation)
class RailwayStationAdmin(admin.ModelAdmin):
    list_display = ("name", "station_code", "country", "active")
    search_fields = ("name", "station_code")


@admin.register(PurchaseContract)
class PurchaseContractAdmin(admin.ModelAdmin):
    list_display = ("number", "supplier", "contract_date", "currency", "active")
    list_filter = ("active", "currency")
    search_fields = ("number", "supplier__name")


class ShipmentWagonInline(admin.TabularInline):
    model = ShipmentWagon
    extra = 0


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "departure_station", "wagon_count", "quantity", "status", "departure_date", "arrival_date")
    list_filter = ("status",)
    inlines = [ShipmentWagonInline]
