from apps.core.access import membership_for


def workspace(request):
    membership = membership_for(request)
    return {
        "workspace": membership,
        "can_edit_catalog": bool(membership and membership.allows("catalog.change_product")),
        "can_open_stock": bool(membership and membership.allows("inventory.add_openingbalance")),
    }

