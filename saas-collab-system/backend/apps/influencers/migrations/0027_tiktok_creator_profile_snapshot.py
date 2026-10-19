from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0026_sampleitem_warehouse"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("masterdata", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TikTokCreatorProfileSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_influencer_id", models.CharField(max_length=160)),
                ("username", models.CharField(blank=True, max_length=255)),
                ("nickname", models.CharField(blank=True, max_length=160)),
                ("follower_count", models.PositiveBigIntegerField(blank=True, null=True)),
                ("selection_region", models.CharField(blank=True, max_length=8)),
                ("identity_status", models.CharField(choices=[("matched", "Matched"), ("handle_mismatch", "Handle mismatch"), ("region_mismatch", "Region mismatch"), ("incomplete", "Incomplete identity")], max_length=24)),
                ("fetched_at", models.DateTimeField()),
                ("fetched_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("influencer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tiktok_creator_snapshots", to="influencers.influencer")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.storemaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("tenant", "influencer", "store"), name="uniq_tiktok_creator_store_snapshot")],
            },
        ),
    ]
