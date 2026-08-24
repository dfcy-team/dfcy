import hashlib

from django.db import migrations, models


def _identity(platform, region, platform_store_id):
    value = f"{str(platform).lower()}:{str(region).upper()}:{str(platform_store_id).strip()}"
    return hashlib.sha256(value.encode()).hexdigest()


def _store_binding(tenant_id, platform, store_id):
    value = f"{tenant_id}:{str(platform).lower()}:{store_id}"
    return hashlib.sha256(value.encode()).hexdigest()


def populate_active_bindings(apps, schema_editor):
    Authorization = apps.get_model("integrations", "MarketplaceStoreAuthorization")
    for record in Authorization.objects.exclude(status="revoked").iterator():
        record.active_platform_identity_key = _identity(
            record.platform, record.region, record.platform_store_id
        )
        record.active_store_binding_key = _store_binding(record.tenant_id, record.platform, record.store_id)
        record.save(update_fields=["active_platform_identity_key", "active_store_binding_key"])


class Migration(migrations.Migration):
    dependencies = [("integrations", "0012_product_mapping")]

    operations = [
        migrations.AddField(
            model_name="marketplacestoreauthorization",
            name="active_platform_identity_key",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="marketplacestoreauthorization",
            name="active_store_binding_key",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.RunPython(populate_active_bindings, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="marketplacestoreauthorization",
            name="uniq_market_store_global_identity",
        ),
        migrations.RemoveConstraint(
            model_name="marketplacestoreauthorization",
            name="uniq_market_store_tenant_link",
        ),
    ]

