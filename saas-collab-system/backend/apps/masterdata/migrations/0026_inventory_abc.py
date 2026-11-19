from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0025_inventory_observation_settings")]
    operations = [
        migrations.AddField(model_name="inventoryobservationsettings", name="abc_enabled", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="inventoryobservationsettings", name="abc_window_days", field=models.PositiveSmallIntegerField(default=90)),
        migrations.AddField(model_name="inventoryobservationsettings", name="abc_a_percent", field=models.DecimalField(max_digits=5, decimal_places=2, default=80)),
        migrations.AddField(model_name="inventoryobservationsettings", name="abc_b_percent", field=models.DecimalField(max_digits=5, decimal_places=2, default=95)),
        migrations.AddField(model_name="inventoryobservationsettings", name="abc_stability_days", field=models.PositiveSmallIntegerField(default=3)),
        migrations.CreateModel(name="InventoryABCRun", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("cutoff_date", models.DateField()), ("window_days", models.PositiveSmallIntegerField(default=90)),
            ("currency", models.CharField(max_length=8, blank=True)), ("status", models.CharField(max_length=16, default="queued")),
            ("config", models.JSONField(default=dict)), ("issues", models.JSONField(default=list)),
            ("net_total", models.DecimalField(max_digits=24, decimal_places=4, default=0)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("completed_at", models.DateTimeField(null=True, blank=True)),
            ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
            ("country", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.countrysitemaster")),
        ], options={"indexes": [models.Index(fields=["tenant", "country", "status", "cutoff_date"], name="abc_run_latest_idx")]}),
        migrations.CreateModel(name="InventoryABCEntry", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("entity_type", models.CharField(max_length=3)), ("entity_id", models.PositiveBigIntegerField()),
            ("grade", models.CharField(max_length=16)), ("candidate_grade", models.CharField(max_length=16, blank=True)),
            ("candidate_streak", models.PositiveSmallIntegerField(default=1)),
            ("revenue", models.DecimalField(max_digits=24, decimal_places=4, null=True)),
            ("share", models.DecimalField(max_digits=18, decimal_places=10, null=True)),
            ("cumulative_share", models.DecimalField(max_digits=18, decimal_places=10, null=True)),
            ("first_sale_date", models.DateField(null=True, blank=True)), ("changed_at", models.DateField(null=True, blank=True)),
            ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="masterdata.inventoryabcrun")),
        ], options={"constraints": [models.UniqueConstraint(fields=["run", "entity_type", "entity_id"], name="abc_entry_run_entity_uniq")]}),
    ]
