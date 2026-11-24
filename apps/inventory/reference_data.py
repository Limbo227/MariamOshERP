"""Repeatable reference rows. Safe to run more than once."""

UNITS = (
    ("PCS", "шт"),
    ("KG", "кг"),
    ("L", "литр"),
    ("BAG", "мешок"),
)

CATEGORIES = (
    ("WHEAT", "Пшеница", "WHEAT", "Зерно"),
    ("FLOUR", "Мука", "FLOUR", "Фасованная и нефасованная мука"),
    ("BYPRODUCT", "Отруби", "BYPRODUCT", "Побочный продукт помола"),
    ("PACKAGING", "Упаковка", "OTHER", "Мешки и упаковочные материалы"),
    ("MATERIAL", "Материалы", "MATERIAL", ""),
    ("SACK", "Пустой мешок", "SACK", ""),
    ("OTHER", "Прочее", "OTHER", ""),
)


def seed_units(model):
    for code, name in UNITS:
        model.objects.update_or_create(code=code, defaults={"name": name, "active": True})


def seed_categories(model):
    for code, name, _role, description in CATEGORIES:
        model.objects.update_or_create(
            code=code,
            defaults={"name": name, "description": description, "active": True},
        )
