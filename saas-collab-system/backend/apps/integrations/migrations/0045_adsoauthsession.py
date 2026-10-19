import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0044_syncjob_affiliate_order"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(name="AdsOAuthSession", fields=[
        ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
        ("state_hash", models.CharField(max_length=64, unique=True)),
        ("config_fingerprint", models.CharField(max_length=64)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("expires_at", models.DateTimeField()),
        ("consumed_at", models.DateTimeField(null=True, blank=True)),
        ("status", models.CharField(max_length=20, default="pending", choices=[
            (v, v) for v in ("pending", "exchanging", "authorized", "unknown", "failed", "bound")])),
        ("credential_id", models.CharField(max_length=160, blank=True)),
        ("token_id", models.CharField(max_length=160, blank=True)),
        ("candidates", models.JSONField(default=list, blank=True)),
        ("binding_request_hash", models.CharField(max_length=64, blank=True)),
        ("binding_results", models.JSONField(default=list, blank=True)),
        *[(name, models.ForeignKey(to=target, on_delete=django.db.models.deletion.PROTECT)) for name, target in [
            ("tenant", "tenants.tenant"), ("store", "masterdata.storemaster"),
            ("integration_config", "integrations.platformintegrationconfig"), ("actor", settings.AUTH_USER_MODEL)]],
    ])]
