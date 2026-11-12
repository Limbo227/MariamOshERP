from django.db import migrations


def seed_cash_operations(apps, schema_editor):
    CashOperation = apps.get_model("finance", "CashOperation")
    CashOperation.objects.bulk_create(
        [
            CashOperation(code="pay-supplier", name="Оплата поставщику", effect="PAY_PARTY"),
            CashOperation(code="receive-customer", name="Поступление от покупателя", effect="RECEIVE_FROM_PARTY"),
            CashOperation(code="electricity", name="Электричество", effect="PAY_EXPENSE"),
            CashOperation(code="tax", name="Налог", effect="PAY_EXPENSE"),
            CashOperation(
                code="deposit-to-bank",
                name="Сдача в банк",
                effect="TRANSFER",
                source_kind="CASH",
                destination_kind="BANK",
            ),
            CashOperation(
                code="withdraw-from-bank",
                name="Снятие из банка",
                effect="TRANSFER",
                source_kind="BANK",
                destination_kind="CASH",
            ),
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_cash_operations, migrations.RunPython.noop),
    ]
