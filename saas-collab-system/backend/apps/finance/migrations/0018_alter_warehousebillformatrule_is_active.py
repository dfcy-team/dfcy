from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0017_archive_bill_format_rules"),
    ]

    operations = [
        migrations.AlterField(
            model_name="warehousebillformatrule",
            name="is_active",
            field=models.BooleanField(db_default=True, default=True),
        ),
    ]
