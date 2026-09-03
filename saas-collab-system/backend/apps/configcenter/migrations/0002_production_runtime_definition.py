from django.db import migrations


CONFIG_KEY = "integrations.production.runtime"

SAFE_DEFAULT = {
    "network": {
        "mode": "",
        "security_approved": False,
        "readonly_sync_enabled": False,
        "allowed_hosts": [],
        "oauth_redirect_allowlist": [],
    },
    "connection": {
        "connect_timeout_seconds": 3.0,
        "read_timeout_seconds": 8.0,
        "max_retries": 2,
        "backoff_base_seconds": 0.5,
        "max_retry_wait_seconds": 8.0,
        "max_total_wait_seconds": 15.0,
    },
    "custody": {
        "backend": "refuse",
        "service_url": "",
        "service_host": "",
        "auth_file_path": "",
        "ca_file_path": "",
    },
    "listing_write": {
        "mode": "disabled",
        "emergency_stop": True,
        "require_batch_approval": True,
        "allowed_platforms": [],
        "allowed_actions": [],
        "allowed_store_ids": [],
        "max_batch_size": 20,
    },
    "platforms": {
        "lazada": {
            "contract_approved": False,
            "app_id": "",
            "redirect_uri": "",
            "auth_url": "https://auth.lazada.com/oauth/authorize",
            "api_host": "https://api.lazada.com",
            "token_path": "/rest/auth/token/create",
            "refresh_path": "/rest/auth/token/refresh",
            "market": "",
        },
        "shopee": {
            "contract_approved": False,
            "app_id": "",
            "redirect_uri": "",
            "auth_url": "https://partner.shopeemobile.com/api/v2/shop/auth_partner",
            "api_host": "https://partner.shopeemobile.com",
            "token_path": "/api/v2/auth/token/get",
            "refresh_path": "/api/v2/auth/access_token/get",
            "revoke_path": "/api/v2/shop/cancel_auth_partner",
            "shop_path": "/api/v2/shop/get_shop_info",
            "order_list_path": "/api/v2/order/get_order_list",
            "order_detail_path": "/api/v2/order/get_order_detail",
            "return_list_path": "/api/v2/returns/get_return_list",
            "return_detail_path": "/api/v2/returns/get_return_detail",
            "market": "",
            "region": "",
        },
        "tiktok": {
            "contract_approved": False,
            "app_id": "",
            "service_id": "",
            "redirect_uri": "",
            "market": "ROW",
            "auth_url": "",
            "api_host": "",
            "auth_urls": {},
            "api_hosts": {},
            "token_host": "https://auth.tiktok-shops.com",
            "token_path": "/api/v2/token/get",
            "refresh_path": "/api/v2/token/refresh",
            "revoke_path": "",
            "authorized_shops_path": "/authorization/202309/shops",
            "metadata_path": "/seller/202309/permissions",
            "order_list_path": "/order/202309/orders/search",
            "order_detail_path": "/order/202309/orders",
            "return_list_path": "/return_refund/202602/returns/search",
        },
    },
}


def seed_production_runtime_definition(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition_model.objects.update_or_create(
        config_key=CONFIG_KEY,
        defaults={
            "scope_type": "system",
            "value_type": "json",
            "default_value": SAFE_DEFAULT,
            "is_sensitive": False,
            "requires_approval": True,
            "description": (
                "系统级生产平台运行时控制。只允许保存网络、端点、路径和审批元数据；"
                "API 同步写入保持关闭；全球刊登生产写入仅通过独立受控策略进入内部队列；"
                "凭据必须由独立密钥托管服务处理。"
            ),
        },
    )


def remove_production_runtime_definition(apps, schema_editor):
    apps.get_model("configcenter", "SystemConfigDefinition").objects.filter(config_key=CONFIG_KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("configcenter", "0001_initial")]
    operations = [migrations.RunPython(seed_production_runtime_definition, remove_production_runtime_definition)]
