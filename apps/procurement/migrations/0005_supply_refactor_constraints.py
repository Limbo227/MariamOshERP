from django.db import migrations, models


class Migration(migrations.Migration):
    """Constraints land in a later transaction than the shipment data copy.

    PostgreSQL refuses to alter shipment in the same transaction that inserted
    wagon rows, because those inserts leave pending foreign-key trigger events.
    """

    dependencies = [
        ("procurement", "0004_copy_legacy_shipments"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="shipment",
            constraint=models.CheckConstraint(
                condition=models.Q(("wagon_count__gte", 1)),
                name="shipment_wagon_count",
            ),
        ),
        migrations.AddConstraint(
            model_name="shipment",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["DRAFT", "POSTED"])),
                name="shipment_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="shipment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("posted_at__isnull", True), ("receipt__isnull", True), ("status", "DRAFT")),
                    models.Q(("posted_at__isnull", False), ("receipt__isnull", False), ("status", "POSTED")),
                    _connector="OR",
                ),
                name="shipment_posted_receipt",
            ),
        ),
        migrations.RemoveField(
            model_name="shipment",
            name="wagon_number",
        ),
        migrations.AddConstraint(
            model_name="shipmentwagon",
            constraint=models.UniqueConstraint(fields=("shipment", "wagon_number"), name="wagon_number_in_shipment"),
        ),
        migrations.AddConstraint(
            model_name="shipmentwagon",
            constraint=models.CheckConstraint(condition=models.Q(("weight_kg__gt", 0)), name="wagon_weight_positive"),
        ),
    ]
