from django.db import migrations


PERMISSION_DEFINITIONS = (
    ("finance.view", "View finance data", "finance", "view", "View finance statements, withdrawals, receipts, matches, and exceptions."),
    ("finance.export", "Export finance data", "finance", "export", "Export authorized finance data."),
    ("finance.import", "Import finance data", "finance", "import", "Import authorized finance data, including phase 2 demo fixtures."),
    ("finance.reconcile", "Reconcile finance data", "finance", "reconcile", "Run and review finance reconciliation suggestions."),
    ("finance.exception.handle", "Handle finance exceptions", "finance", "exception.handle", "Handle finance reconciliation exceptions."),
    ("integrations.view", "View integrations", "integrations", "view", "View integration configuration metadata and synchronization runs."),
    ("integrations.manage", "Manage integrations", "integrations", "manage", "Create, update, verify, or disable integration configurations and jobs."),
    ("integrations.rotate", "Rotate integration credentials", "integrations", "rotate", "Rotate encrypted integration credentials."),
    ("integrations.run", "Run integration synchronization", "integrations", "run", "Run phase 2 mock integration synchronization jobs."),
    ("suppliers.performance.view", "View supplier performance", "suppliers", "performance.view", "View supplier performance within the assigned data scope."),
    ("suppliers.performance.calculate", "Calculate supplier performance", "suppliers", "performance.calculate", "Calculate phase 2 mock supplier performance snapshots."),
    ("products.status.view", "View product status", "products", "status.view", "View product status recommendations and transitions."),
    ("products.status.evaluate", "Evaluate product status", "products", "status.evaluate", "Generate product status recommendations from phase 2 mock metrics."),
    ("products.status.confirm", "Confirm product status", "products", "status.confirm", "Confirm or reject standard product status recommendations."),
    ("products.status.high_risk_confirm", "Confirm high-risk product status", "products", "status.high_risk_confirm", "Confirm clearance, stopped, or archived product status recommendations."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSION_DEFINITIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0001_initial")]

    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
