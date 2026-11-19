from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0024_backfill_platform_connectors")]
    operations = [migrations.CreateModel(name="InventoryObservationSettings", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("new_product_observation_days", models.PositiveSmallIntegerField(default=30)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        ("tenant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_observation_settings", to="tenants.tenant")),
    ])]
