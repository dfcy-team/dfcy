from django.db import migrations, models
import django.db.models.functions.text


LEGACY_CONSTRAINT_NAME = "uniq_held_rpa_platform_account"


def drop_legacy_constraint_if_present(apps, schema_editor):
    account_lock = apps.get_model("rpa", "RPAAccountLock")
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor,
            account_lock._meta.db_table,
        )
    if LEGACY_CONSTRAINT_NAME not in constraints:
        return

    legacy_constraint = next(
        constraint
        for constraint in account_lock._meta.constraints
        if constraint.name == LEGACY_CONSTRAINT_NAME
    )
    schema_editor.remove_constraint(account_lock, legacy_constraint)


def restore_legacy_constraint_if_supported(apps, schema_editor):
    if not schema_editor.connection.features.supports_partial_indexes:
        return

    account_lock = apps.get_model("rpa", "RPAAccountLock")
    legacy_constraint = next(
        constraint
        for constraint in account_lock._meta.constraints
        if constraint.name == LEGACY_CONSTRAINT_NAME
    )
    schema_editor.add_constraint(account_lock, legacy_constraint)


class Migration(migrations.Migration):
    dependencies = [
        ("rpa", "0004_ui_p3_device_and_manual_assignment"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    drop_legacy_constraint_if_present,
                    restore_legacy_constraint_if_supported,
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="rpaaccountlock",
                    name=LEGACY_CONSTRAINT_NAME,
                ),
            ],
        ),
        migrations.AddField(
            model_name="rpaaccountlock",
            name="held_lock_key",
            field=models.GeneratedField(
                db_persist=True,
                expression=models.Case(
                    models.When(
                        lock_status="held",
                        then=django.db.models.functions.text.Concat(
                            "platform",
                            models.Value("\x1f"),
                            "account_alias",
                        ),
                    ),
                    default=models.Value(None),
                    output_field=models.CharField(max_length=161),
                ),
                null=True,
                output_field=models.CharField(max_length=161),
            ),
        ),
        migrations.AddConstraint(
            model_name="rpaaccountlock",
            constraint=models.UniqueConstraint(
                fields=("tenant", "held_lock_key"),
                name=LEGACY_CONSTRAINT_NAME,
            ),
        ),
    ]
