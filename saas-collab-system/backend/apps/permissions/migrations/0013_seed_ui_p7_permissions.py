from django.db import migrations


PERMISSIONS = (
    ("governance.api.view", "View API contracts", "governance", "api.view", "View tenant and data-scope filtered API contracts."),
    ("governance.api.check", "Check API contracts", "governance", "api.check", "Run fixed dry-run API contract checks without business writes."),
    ("governance.assistants.view", "View assistant governance", "governance", "assistants.view", "View assistant capability and safety definitions."),
    ("governance.assistants.evaluate", "Evaluate assistant definitions", "governance", "assistants.evaluate", "Run fixed assistant governance dry-runs without tool execution."),
    ("pilot.readiness.view", "View pilot readiness", "pilot", "readiness.view", "View controlled pilot readiness evidence."),
    ("pilot.topology.view", "View pilot topology", "pilot", "topology.view", "View masked controlled-pilot topology metadata."),
    ("pilot.topology.verify", "Verify pilot topology", "pilot", "topology.verify", "Run fixed topology dry-run validation without remote execution."),
    ("pilot.recovery.view", "View recovery plans", "pilot", "recovery.view", "View authorized recovery plans and drill evidence."),
    ("pilot.recovery.plan", "Plan recovery drills", "pilot", "recovery.plan", "Create and submit recovery plans without executing infrastructure commands."),
    ("pilot.recovery.review", "Review recovery plans", "pilot", "recovery.review", "Approve or reject recovery plans with separation of duties."),
    ("pilot.recovery.record", "Record recovery evidence", "pilot", "recovery.record", "Record externally performed recovery drill outcomes."),
    ("pilot.release.view", "View release plans", "pilot", "release.view", "View authorized controlled-pilot release plans."),
    ("pilot.release.plan", "Plan pilot releases", "pilot", "release.plan", "Create release plans without performing deployment."),
    ("pilot.release.review", "Review pilot releases", "pilot", "release.review", "Approve or reject controlled-pilot release plans."),
    ("pilot.release.record", "Record release evidence", "pilot", "release.record", "Record externally performed release outcomes."),
    ("pilot.release.rollback", "Review and record rollback", "pilot", "release.rollback", "Approve and record externally performed rollback outcomes."),
    ("pilot.capacity.view", "View pilot capacity", "pilot", "capacity.view", "View tenant and scope filtered capacity observations."),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0012_seed_ui_p5_business_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
