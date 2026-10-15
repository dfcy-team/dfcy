from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.using(schema_editor.connection.alias).update_or_create(
        code="menu.supply.supply_chain_supplier_shipments.view",
        defaults={"name": "供应商发货单", "module": "supply", "action": "supply_chain_supplier_shipments.view",
                  "description": "显示供应商发货单入口", "permission_type": "menu",
                  "metadata": {"path": "/supply-chain/supplier-shipments", "route": "/supply-chain/supplier-shipments",
                               "resource": "supply_chain_supplier_shipments", "parent": "供应链协同",
                               "action_codes": ["supply.v2.view"], "source": "frontend/src/router/menu.js", "status": "active"}})
    # Register only. Existing roles/grants are preserved; no account gains access.


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0005_boxinfoattachment_is_active_shipmentline_is_active_and_more")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
