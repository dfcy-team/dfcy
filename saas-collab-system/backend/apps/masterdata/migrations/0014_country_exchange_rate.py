from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0013_store_external_identity_constraint")]

    operations = [
        migrations.AddField(
            model_name="countrysitemaster",
            name="cny_exchange_rate",
            field=models.DecimalField(blank=True, decimal_places=10, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name="countrysitemaster",
            name="exchange_rate_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="countrysitemaster",
            name="exchange_rate_source",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="countrysitemaster",
            name="exchange_rate_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
