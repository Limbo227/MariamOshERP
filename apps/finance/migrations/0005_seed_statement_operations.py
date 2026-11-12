from django.db import migrations


def seed_statement_operations(apps, schema_editor):
    CashOperation = apps.get_model("finance", "CashOperation")
    CashOperation.objects.bulk_create(
        [
            CashOperation(code="convert", name="Обмен валюты", effect="CONVERT"),
            CashOperation(code="bank-commission", name="Банковская комиссия", effect="PAY_EXPENSE"),
            CashOperation(code="swift", name="Комиссия SWIFT", effect="PAY_EXPENSE"),
            CashOperation(code="water", name="Вода", effect="PAY_EXPENSE"),
            CashOperation(code="railway", name="Железная дорога", effect="PAY_EXPENSE"),
            CashOperation(code="salary", name="Зарплата", effect="PAY_EXPENSE"),
            CashOperation(
                code="qr-settlement",
                name="Зачисление QR",
                effect="TRANSFER",
                source_kind="BANK",
                destination_kind="BANK",
            ),
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0004_remove_cashoperation_operation_effect_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_statement_operations, migrations.RunPython.noop),
    ]
