import hashlib

from django.db import migrations


def _api_type(config):
    value = str((config.platform_config or {}).get("api_type") or "marketplace")
    return value.strip().lower() or "marketplace"


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _keys(record, api_type):
    identity = f"{record.platform.lower()}:{record.region.upper()}:{record.platform_store_id.strip()}"
    store = f"{record.tenant_id}:{record.platform.lower()}:{record.store_id}"
    if api_type != "marketplace":
        identity = f"{identity}:{api_type}"
        store = f"{store}:{api_type}"
    return _digest(identity), _digest(store)


def forwards(apps, schema_editor):
    Authorization = apps.get_model("integrations", "MarketplaceStoreAuthorization")
    for record in Authorization.objects.exclude(status="revoked").select_related("integration_config").iterator():
        active_identity, active_store = _keys(record, _api_type(record.integration_config))
        Authorization.objects.filter(pk=record.pk).update(
            active_platform_identity_key=active_identity,
            active_store_binding_key=active_store,
        )


def backwards(apps, schema_editor):
    Authorization = apps.get_model("integrations", "MarketplaceStoreAuthorization")
    seen_identities = set()
    seen_stores = set()
    rows = list(Authorization.objects.exclude(status="revoked").iterator())
    for record in rows:
        active_identity, active_store = _keys(record, "marketplace")
        if active_identity in seen_identities or active_store in seen_stores:
            raise RuntimeError("Cannot collapse independent API authorization slots during rollback.")
        seen_identities.add(active_identity)
        seen_stores.add(active_store)
    for record in rows:
        active_identity, active_store = _keys(record, "marketplace")
        Authorization.objects.filter(pk=record.pk).update(
            active_platform_identity_key=active_identity,
            active_store_binding_key=active_store,
        )


class Migration(migrations.Migration):
    dependencies = [("integrations", "0032_internal_api_client")]

    operations = [migrations.RunPython(forwards, backwards)]
