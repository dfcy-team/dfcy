from django.db import migrations


PERMISSIONS = (
    ("workflow.approvals.view", "View workflow approvals", "approvals.view", "View tenant and permission-specific data-scope filtered approvals."),
    ("workflow.approvals.submit", "Submit mock workflow approvals", "approvals.submit", "Submit audited mock approval requests without executing business actions."),
    ("workflow.approvals.review", "Review workflow approvals", "approvals.review", "Approve or reject authorized approvals with requester/reviewer separation."),
    ("workflow.approvals.withdraw", "Withdraw workflow approvals", "approvals.withdraw", "Withdraw the actor's own pending approval requests."),
    ("workflow.exceptions.view", "View workflow exceptions", "exceptions.view", "View tenant and module scoped exception records."),
    ("workflow.exceptions.manage", "Manage workflow exceptions", "exceptions.manage", "Assign, resolve and close authorized exception records."),
    ("workflow.collaboration.view", "View collaboration feedback", "collaboration.view", "View masked mock collaboration feedback awaiting confirmation."),
    ("workflow.collaboration.confirm", "Confirm collaboration feedback", "collaboration.confirm", "Confirm or reject mock feedback without directly writing business state."),
    ("reports.download", "Download audited report placeholders", "download", "Request short-lived placeholder download references with tenant, data-scope and audit checks."),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "workflow" if code.startswith("workflow.") else "reports", "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0010_seed_ui_p3_rpa_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
