from django.db import migrations


PERMISSIONS = (
    ("supply.shipment.view", "View shipments", "shipment.view"),
    ("supply.shipment.create", "Create shipments", "shipment.create"),
    ("supply.shipment.update", "Update shipment drafts", "shipment.update"),
    ("supply.shipment.allocate", "Allocate shipment boxes", "shipment.allocate"),
    ("supply.shipment.customs.confirm", "Confirm shipment customs declaration", "shipment.customs.confirm"),
    ("supply.shipment.dispatch", "Dispatch shipment boxes", "shipment.dispatch"),
    ("supply.shipment.port_arrival.confirm", "Confirm shipment port arrival", "shipment.port_arrival.confirm"),
    ("supply.shipment.warehouse_arrival.confirm", "Confirm shipment warehouse arrival", "shipment.warehouse_arrival.confirm"),
    ("supply.shipment.clearance.complete", "Complete shipment clearance", "shipment.clearance.complete"),
    ("supply.shipment.exception.manage", "Manage shipment exceptions", "shipment.exception.manage"),
    ("supply.shipment.cancel", "Cancel shipments", "shipment.cancel"),
)


def seed_permissions(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    for code, name, action in PERMISSIONS:
        permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "supply",
                "action": action,
                "description": "SC-SHIPMENT-1 frozen local-domain permission.",
            },
        )


def remove_permissions(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    permission.objects.filter(code__in=[code for code, _, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("permissions", "0025_seed_consolidation_permissions")]
    operations = [migrations.RunPython(seed_permissions, remove_permissions)]
