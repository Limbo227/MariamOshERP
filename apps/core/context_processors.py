from apps.core.access import membership_for


def workspace(request):
    membership = membership_for(request)
    flags = {
        "can_edit_catalog": "catalog.change_product",
        "can_open_stock": "inventory.add_openingbalance",
        "can_view_stock": "inventory.view_stockledgerentry",
        "can_view_products": "catalog.view_product",
        "can_add_products": "catalog.add_product",
        "can_view_suppliers": "catalog.view_supplier",
        "can_add_suppliers": "catalog.add_supplier",
        "can_view_stations": "catalog.view_originstation",
        "can_add_stations": "catalog.add_originstation",
        "can_view_contracts": "procurement.view_supplycontract",
        "can_add_contracts": "procurement.add_supplycontract",
        "can_view_openings": "inventory.view_openingbalance",
        "can_view_warehouses": "inventory.view_warehouse",
        "can_view_orders": "procurement.view_purchaseorder",
        "can_add_orders": "procurement.add_purchaseorder",
        "can_confirm_orders": "procurement.confirm_purchaseorder",
        "can_view_prices": "procurement.view_purchaseprice",
        "can_view_shipments": "procurement.view_shipment",
        "can_manage_shipments": "procurement.add_shipment",
        "can_view_receipts": "inventory.view_goodsreceipt",
        "can_receive": "inventory.add_goodsreceipt",
        "can_view_exceptions": "quality.view_exceptionrecord",
        "can_adjust": "inventory.add_stockadjustment",
        "can_release": "quality.add_releasedecision",
    }
    data = {"workspace": membership}
    for key, permission in flags.items():
        data[key] = bool(membership and membership.allows(permission))
    return data
