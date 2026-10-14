from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0026_sampleitem_warehouse"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InfluencerPlatformAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("tiktok", "TikTok"), ("facebook", "Facebook"), ("instagram", "Instagram"), ("youtube", "YouTube")], max_length=20)),
                ("handle", models.CharField(blank=True, max_length=255)),
                ("external_account_id", models.CharField(blank=True, max_length=160)),
                ("display_name", models.CharField(blank=True, max_length=160)),
                ("profile_url", models.URLField(blank=True, max_length=500)),
                ("follower_count", models.PositiveBigIntegerField(blank=True, null=True, validators=[MinValueValidator(0)])),
                ("is_active", models.BooleanField(default=True)),
                ("source", models.CharField(default="manual", max_length=40)),
                ("active_handle_digest", models.CharField(blank=True, editable=False, max_length=64, null=True)),
                ("active_external_id_digest", models.CharField(blank=True, editable=False, max_length=64, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("influencer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="platform_accounts", to="influencers.influencer")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="platform_accounts_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="platform_accounts_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["platform", "id"],
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "influencer", "platform"), name="uniq_inf_platform_slot"),
                    models.UniqueConstraint(fields=("tenant", "platform", "active_handle_digest"), name="uniq_inf_platform_handle"),
                    models.UniqueConstraint(fields=("tenant", "platform", "active_external_id_digest"), name="uniq_inf_platform_external"),
                    models.CheckConstraint(condition=models.Q(follower_count__isnull=True) | models.Q(follower_count__gte=0), name="chk_inf_platform_followers"),
                ],
            },
        ),
    ]
