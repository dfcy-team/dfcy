from copy import deepcopy

from django.db import migrations


CONFIG_KEY = "integrations.production.runtime"
PRODUCT_DEFAULTS = {
    "shopee": {
        "product_contract_approved": False,
        "product_list_path": "/api/v2/product/get_item_list",
        "product_base_info_path": "/api/v2/product/get_item_base_info",
        "product_model_list_path": "/api/v2/product/get_model_list",
    },
    "tiktok": {
        "product_contract_approved": False,
        "product_search_path": "/product/202502/products/search",
        "product_detail_path": "/product/202309/products/{product_id}",
    },
}


def add_product_endpoint_defaults(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition = definition_model.objects.filter(config_key=CONFIG_KEY).first()
    if definition is None:
        return
    value = deepcopy(definition.default_value) if isinstance(definition.default_value, dict) else {}
    platforms = value.setdefault("platforms", {})
    changed = False
    for platform, defaults in PRODUCT_DEFAULTS.items():
        target = platforms.setdefault(platform, {})
        for key, endpoint in defaults.items():
            if key not in target:
                target[key] = endpoint
                changed = True
    if changed:
        definition.default_value = value
        definition.save(update_fields=["default_value", "updated_at"])


def remove_product_endpoint_defaults(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition = definition_model.objects.filter(config_key=CONFIG_KEY).first()
    if definition is None or not isinstance(definition.default_value, dict):
        return
    value = deepcopy(definition.default_value)
    platforms = value.get("platforms") or {}
    changed = False
    for platform, defaults in PRODUCT_DEFAULTS.items():
        target = platforms.get(platform) or {}
        for key in defaults:
            if key in target:
                target.pop(key, None)
                changed = True
    if changed:
        definition.default_value = value
        definition.save(update_fields=["default_value", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("configcenter", "0002_production_runtime_definition")]

    operations = [migrations.RunPython(add_product_endpoint_defaults, remove_product_endpoint_defaults)]
