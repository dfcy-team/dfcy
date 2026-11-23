from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0027_inventory_abc_composite"),
    ]

    operations = [
        migrations.AlterField(
            model_name="inventoryabcentry",
            name="evidence",
            field=models.JSONField(
                blank=True, default=dict,
                db_default=models.Func(function="JSON_OBJECT", output_field=models.JSONField()),
            ),
        ),
    ]
