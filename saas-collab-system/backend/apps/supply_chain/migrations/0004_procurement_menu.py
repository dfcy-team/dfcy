from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.using(schema_editor.connection.alias).update_or_create(
        code="menu.supply.supply_chain_purchase_orders.view",
        defaults={
            "name": "采购协同", "module": "supply",
            "action": "supply_chain_purchase_orders.view",
            "description": "显示采购协同入口", "permission_type": "menu",
            "metadata": {
                "path": "/supply-chain/purchase-orders",
                "route": "/supply-chain/purchase-orders",
                "resource": "supply_chain_purchase_orders",
                "parent": "供应链协同", "action_codes": ["supply.v2.view"],
                "source": "frontend/src/router/menu.js", "status": "active",
            },
        },
    )
    # Keep existing menu grants. Never provision or grant procurement actions.


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0003_purchaseline_is_active_supplierproductprice_and_more")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
