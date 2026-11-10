from django.contrib import admin

from apps.procurement.models import (
    AmendmentLine,
    ContractLine,
    ContractPayment,
    ContractShipment,
    CustomsAcceptance,
    FactoryArrival,
    OrderAmendment,
    OrderLine,
    PurchaseCharge,
    PurchaseOrder,
    Shipment,
    SupplyContract,
    TransportUnit,
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


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(InspectOnlyAdmin):
    list_display = ("reference", "company", "supplier", "state", "effective_date")


@admin.register(OrderLine)
class OrderLineAdmin(InspectOnlyAdmin):
    list_display = ("order", "product", "quantity", "unit_price")


@admin.register(OrderAmendment)
class OrderAmendmentAdmin(InspectOnlyAdmin):
    list_display = ("order", "revision", "reason")


@admin.register(AmendmentLine)
class AmendmentLineAdmin(InspectOnlyAdmin):
    list_display = ("amendment", "order_line", "new_quantity", "new_price")


@admin.register(CustomsAcceptance)
class CustomsAcceptanceAdmin(InspectOnlyAdmin):
    list_display = ("order", "port", "quantity", "accepted_on")


@admin.register(Shipment)
class ShipmentAdmin(InspectOnlyAdmin):
    list_display = ("reference", "company", "supplier", "state")


@admin.register(TransportUnit)
class TransportUnitAdmin(InspectOnlyAdmin):
    list_display = ("identifier", "shipment", "declared_quantity")


@admin.register(PurchaseCharge)
class PurchaseChargeAdmin(InspectOnlyAdmin):
    list_display = ("counterparty", "shipment", "amount")


@admin.register(SupplyContract)
class SupplyContractAdmin(InspectOnlyAdmin):
    list_display = ("number", "supplier", "currency")


@admin.register(ContractLine)
class ContractLineAdmin(InspectOnlyAdmin):
    list_display = ("contract", "product", "quantity", "price")


@admin.register(ContractShipment)
class ContractShipmentAdmin(InspectOnlyAdmin):
    list_display = ("line", "station", "wagon_count", "quantity")


@admin.register(FactoryArrival)
class FactoryArrivalAdmin(InspectOnlyAdmin):
    list_display = ("shipment", "warehouse", "arrived_on")


@admin.register(ContractPayment)
class ContractPaymentAdmin(InspectOnlyAdmin):
    list_display = ("contract", "paid_on", "amount")
