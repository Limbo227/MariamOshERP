from django.db import migrations


def copy_shipments(apps, schema_editor):
    """Old transit statuses never posted stock. Keep every historical shipment a draft.

    A recorded wagon number is copied with the shipment weight already stored on that
    row. Missing stations and missing wagon numbers stay empty; nothing is invented.
    """

    Shipment = apps.get_model("procurement", "Shipment")
    ShipmentWagon = apps.get_model("procurement", "ShipmentWagon")
    PurchaseContract = apps.get_model("procurement", "PurchaseContract")
    PurchaseOrder = apps.get_model("procurement", "PurchaseOrder")
    Shipment.objects.update(status="DRAFT", posted_at=None, details_complete=False)
    for shipment in Shipment.objects.all().iterator():
        number = (shipment.wagon_number or "").strip()
        if not number:
            continue
        ShipmentWagon.objects.create(
            shipment_id=shipment.pk,
            wagon_number=number,
            weight_kg=shipment.quantity,
        )
        Shipment.objects.filter(pk=shipment.pk).update(wagon_count=1, details_complete=True)
    for contract in PurchaseContract.objects.all().iterator():
        currencies = list(
            PurchaseOrder.objects.filter(contract_id=contract.pk).values_list("currency", flat=True).distinct()
        )
        if len(currencies) == 1 and currencies[0]:
            PurchaseContract.objects.filter(pk=contract.pk).update(currency=currencies[0])


def restore_shipments(apps, schema_editor):
    Shipment = apps.get_model("procurement", "Shipment")
    ShipmentWagon = apps.get_model("procurement", "ShipmentWagon")
    for shipment in Shipment.objects.all().iterator():
        wagon = ShipmentWagon.objects.filter(shipment_id=shipment.pk).order_by("pk").first()
        Shipment.objects.filter(pk=shipment.pk).update(
            wagon_number=wagon.wagon_number if wagon is not None else "",
            status="IN_TRANSIT",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0003_supply_refactor"),
    ]

    operations = [
        migrations.RunPython(copy_shipments, restore_shipments),
    ]
