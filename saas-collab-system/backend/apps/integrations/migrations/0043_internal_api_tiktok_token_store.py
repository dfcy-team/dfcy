from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0042_merge_tiktok_pilot_20261007"),
        ("masterdata", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="internalapiclient",
            name="tiktok_token_store",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="tiktok_token_clients", to="masterdata.storemaster",
            ),
        ),
        migrations.CreateModel(
            name="TikTokTokenLeaseAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("authorization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.marketplacestoreauthorization")),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.internalapiclient")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
            ],
        ),
    ]
