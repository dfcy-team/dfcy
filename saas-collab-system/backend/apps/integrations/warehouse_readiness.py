"""Non-secret warehouse gates shared by approval and live authorization."""

from urllib.parse import urlsplit

from django.conf import settings

from apps.common.module_gate import is_module_enabled

from .capability import approved_custody_configured
from .production_settings import get_runtime_platform_config, get_runtime_setting


WAREHOUSE_BLOCKER_LABELS = {
    "integration_module_disabled": "API 数据接入模块未启用",
    "debug_enabled": "当前后端启用了 DEBUG，不能进行真实授权",
    "warehouse_api_url_invalid": "极风 API Base URL 未填写或格式不正确",
    "warehouse_host_not_allowlisted": "仓库 API 域名未加入出站白名单",
    "best_feature_disabled": "百世真实调用未开启",
    "best_contract_invalid": "百世配置须使用 GLINK 协议",
    "best_identity_missing": "百世 partnerId 或客户编码未配置",
    "best_gateway_invalid": "百世网关与配置环境不匹配",
    "warehouse_domain_missing": "极风公共配置缺少 Domain",
    "warehouse_client_id_missing": "极风公共配置缺少 Client ID",
}


def warehouse_config_blockers(config):
    """No secret retrieval, DNS lookup, platform calls or warehouse-token checks."""
    values = dict(config.platform_config or {})
    blockers = []
    if not is_module_enabled("api_integrations"):
        blockers.append("integration_module_disabled")
    if settings.DEBUG:
        blockers.append("debug_enabled")
    if config.environment not in {"pilot", "production"}:
        blockers.append("environment_not_live")
    if config.status not in {"verified", "active"}:
        blockers.append("config_not_approved")
    for key, expected, code in (
        ("mode", "approved-live-test", "platform_network_mode_disabled"),
        ("security_approved", True, "platform_security_not_approved"),
        ("readonly_sync_enabled", True, "readonly_sync_feature_disabled"),
    ):
        if get_runtime_setting("network", key, default=None) != expected:
            blockers.append(code)
    if not approved_custody_configured():
        blockers.append("credential_custody_not_approved")
    if not get_runtime_platform_config(config.platform).get("contract_approved", False):
        blockers.append("platform_contract_not_enabled")
    if not config.network_enabled:
        blockers.append("network_not_approved")
    if not config.sync_read_enabled:
        blockers.append("readonly_not_approved")
    if config.sync_write_enabled:
        blockers.append("write_sync_enabled")
    if getattr(config, "credential_status", "") != "configured":
        blockers.append("credential_not_configured")
    if not getattr(config, "credential_id", ""):
        blockers.append("credential_reference_missing")
    if config.platform == "best_ecapi":
        from .best_glink import GATEWAYS
        from .net_guard import get_allowed_hosts
        if not getattr(settings, "BEST_ECAPI_ENABLED", False):
            blockers.append("best_feature_disabled")
        if config.contract_version != "glink":
            blockers.append("best_contract_invalid")
        if any(not str(values.get(key) or "").strip() for key in ("partner_id", "customer_code")):
            blockers.append("best_identity_missing")
        expected = GATEWAYS.get(config.environment)
        if not expected or values.get("api_host") != expected:
            blockers.append("best_gateway_invalid")
        elif urlsplit(expected).hostname not in get_allowed_hosts():
            blockers.append("warehouse_host_not_allowlisted")
        return blockers
    try:
        url = urlsplit(str(values.get("api_host") or "").strip())
        valid_url = (url.scheme == "https" and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment and url.path.rstrip("/") in {"", "/api"}
            and url.port in {None, 443})
    except ValueError:
        valid_url = False
    if not valid_url:
        blockers.append("warehouse_api_url_invalid")
    elif url.hostname.lower() not in {
        str(host).lower() for host in get_runtime_setting("network", "allowed_hosts", default=[]) or []
    }:
        blockers.append("warehouse_host_not_allowlisted")
    for key in ("domain", "client_id"):
        if not str(values.get(key) or "").strip():
            blockers.append(f"warehouse_{key}_missing")
    return blockers
