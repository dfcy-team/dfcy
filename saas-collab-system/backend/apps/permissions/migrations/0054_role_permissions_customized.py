from django.db import migrations, models


def freeze_existing_administrators(apps, schema_editor):
    Role = apps.get_model("permissions", "Role")
    database = schema_editor.connection.alias
    last_pk = None
    while True:
        batch = Role.objects.using(database).filter(code="administrator")
        if last_pk is not None:
            batch = batch.filter(pk__gt=last_pk)
        role_ids = list(batch.order_by("pk").values_list("pk", flat=True)[:1000])
        if not role_ids:
            break
        Role.objects.using(database).filter(pk__in=role_ids).update(permissions_customized=True)
        last_pk = role_ids[-1]


class Migration(migrations.Migration):
    dependencies = [("permissions", "0053_register_sales_realtime_board_menu")]

    operations = [
        migrations.AddField(
            model_name="role",
            name="permissions_customized",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(freeze_existing_administrators, migrations.RunPython.noop),
    ]
