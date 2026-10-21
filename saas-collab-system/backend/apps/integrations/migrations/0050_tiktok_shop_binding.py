import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0049_feishubusinessreminder_and_more"),
        ("masterdata", "0018_archive_code_rule"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name=model, name=name, field=field)
        for model in ("oauthstatesession", "adsoauthsession")
        for name, field in (
            ("browser_verifier_hash", models.CharField(blank=True, default="", max_length=64)),
            ("callback_transport", models.CharField(default="legacy", max_length=16)),
        )
    ] + [
        migrations.CreateModel(
            name="TikTokShopBindingSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("operation_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("status", models.CharField(choices=[("exchanging", "Exchanging"), ("pending_confirmation", "Pending confirmation"), ("bound", "Bound"), ("cancelled", "Cancelled"), ("cleanup_pending", "Cleanup pending"), ("cleaning", "Cleaning"), ("cleaned", "Cleaned")], default="exchanging", max_length=24)),
                ("region", models.CharField(max_length=8)),
                ("configuration_digest", models.CharField(max_length=64)),
                ("store_identity", models.JSONField(default=dict)),
                ("exchange_data", models.JSONField(blank=True, default=dict)),
                ("expires_at", models.DateTimeField()),
                ("selected_platform_store_id", models.CharField(blank=True, max_length=160)),
                ("cleanup_fence", models.UUIDField(blank=True, null=True)),
                ("cleanup_lease_until", models.DateTimeField(blank=True, null=True)),
                ("cleanup_attempts", models.PositiveIntegerField(default=0)),
                ("cleanup_error", models.CharField(blank=True, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("authorization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="integrations.marketplacestoreauthorization")),
                ("initiated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("integration_config", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.platformintegrationconfig")),
                ("oauth_session", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="shop_binding", to="integrations.oauthstatesession")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.storemaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
            ],
            options={"indexes": [models.Index(fields=["status", "expires_at"], name="idx_tiktok_binding_cleanup")]},
        ),
    ]
