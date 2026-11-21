from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_payment_approval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="payment_approval_required",
            field=models.BooleanField(db_default=True, default=True),
        ),
        migrations.AlterField(
            model_name="tenant",
            name="payment_approval_version",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
    ]
