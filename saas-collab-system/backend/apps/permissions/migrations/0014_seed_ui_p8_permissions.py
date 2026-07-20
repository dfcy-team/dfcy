from django.db import migrations


PERMISSIONS = (
    ("pilot.control.view", "View pilot control room", "control.view", "View masked production-pilot readiness evidence."),
    ("pilot.security_review.view", "View pilot security reviews", "security_review.view", "View scoped security review evidence."),
    ("pilot.security_review.plan", "Plan pilot security reviews", "security_review.plan", "Create and submit scoped security reviews."),
    ("pilot.security_review.review", "Review pilot security reviews", "security_review.review", "Approve or reject security reviews with separation of duties."),
    *((f"pilot.verification.{action}", f"{action.title()} pilot verification", f"verification.{action}", f"{action.title()} scoped pilot verification records without external execution.") for action in ("view", "plan", "review", "record", "cancel")),
    *((f"pilot.performance.{action}", f"{action.title()} pilot performance", f"performance.{action}", f"{action.title()} scoped pilot performance records without external execution.") for action in ("view", "plan", "review", "record", "cancel")),
    *((f"pilot.entry.{action}", f"{action.title()} pilot entry", f"entry.{action}", f"{action.title()} scoped pilot entry records without external execution.") for action in ("view", "plan", "review")),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "pilot",
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0013_seed_ui_p7_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
