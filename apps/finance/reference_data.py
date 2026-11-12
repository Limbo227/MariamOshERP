EXPENSE_CATEGORIES = (
    ("RAIL", "Железнодорожные расходы", "Расходы железной дороги по поставке"),
    ("TRANSPORT", "Транспортные расходы", ""),
    ("SUPPLY", "Прочие расходы по поставке", ""),
    ("BANK", "Банковские комиссии", ""),
    ("OPERATING", "Операционные расходы", ""),
)


def seed_expense_categories(model):
    for code, name, description in EXPENSE_CATEGORIES:
        model.objects.update_or_create(
            code=code,
            defaults={"name": name, "description": description, "active": True},
        )


def seed_shipment_operation(model):
    model.objects.update_or_create(
        code="shipment-expense",
        defaults={
            "name": "Расход поставки",
            "effect": "SHIPMENT_EXPENSE",
            "category": "",
            "source_kind": "",
            "destination_kind": "",
            "active": True,
        },
    )
