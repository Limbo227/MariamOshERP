from apps.core.access import membership_for


def workspace(request):
    membership = membership_for(request)
    flags = {
        "can_edit_catalog": "catalog.change_product",
        "can_open_stock": "inventory.add_openingbalance",
        "can_view_stock": "inventory.view_stockledgerentry",
        "can_view_products": "catalog.view_product",
        "can_view_suppliers": "catalog.view_supplier",
        "can_view_openings": "inventory.view_openingbalance",
        "can_view_warehouses": "inventory.view_warehouse",
    }
    data = {"workspace": membership}
    for key, permission in flags.items():
        data[key] = bool(membership and membership.allows(permission))
    return data
