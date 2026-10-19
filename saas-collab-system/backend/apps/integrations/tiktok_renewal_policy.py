"""Exact ownership of imported Shop credentials; never applies to Ads tokens."""


def binding_matches(record, bindings, *, require_config=False):
    identity = {
        "tenant_id": record.tenant_id,
        "store_code": record.store.code,
        "region": record.region,
        "platform_store_id": record.platform_store_id,
    }
    for binding in bindings:
        if not isinstance(binding, dict) or any(binding.get(key) != value for key, value in identity.items()):
            continue
        config_id = binding.get("integration_config_id")
        if require_config and config_id is None:
            continue
        if config_id is not None and config_id != record.integration_config_id:
            continue
        return True
    return False
