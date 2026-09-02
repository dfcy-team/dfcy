"""Read-only production readiness projection for marketplace integrations.

The projection intentionally reports facts already enforced by the OAuth/live
provider gates.  It never enables network access, approves a configuration, or
returns credential material.
"""

from collections import defaultdict

from django.conf import settings

from .capability import approved_custody_configured, live_network_mode_enabled
from .live_providers import integration_config_oauth_blockers


MARKETPLACE_PLATFORMS = (
    ("lazada", "Lazada"),
    ("shopee", "Shopee"),
    ("tiktok", "TikTok Shop"),
)

BLOCKER_LABELS = {
    "config_missing": "尚未创建接入配置",
    "platform_mismatch": "配置平台不匹配",
    "environment_not_live": "配置不是试运行或生产环境",
    "platform_network_mode_disabled": "生产平台只读网络模式未启用",
    "platform_security_not_approved": "生产平台安全审批未通过",
    "credential_custody_not_approved": "密钥托管服务未通过检查",
    "outbound_host_allowlist_missing": "平台出站域名白名单未配置",
    "platform_contract_not_enabled": "平台合同开关未启用",
    "network_not_approved": "当前配置的网络访问未批准",
    "write_sync_enabled": "当前配置异常启用了写同步",
    "config_not_approved": "接入配置尚未审核通过",
    "credential_not_configured": "开发者凭据尚未配置",
    "credential_reference_missing": "开发者凭据引用缺失",
    "contract_not_approved": "接口合同版本不符合当前平台要求",
    "callback_missing": "授权回调地址未填写",
    "callback_allowlist_missing": "授权回调白名单未配置",
    "callback_mismatch": "授权回调地址与服务器配置不一致",
    "callback_not_allowlisted": "授权回调地址不在白名单内",
    "public_app_id_missing": "平台应用 ID 未填写",
}


def _config_summary(configs):
    if not configs:
        return "未配置"
    live = sum(config.environment in {"pilot", "production"} for config in configs)
    return f"共 {len(configs)} 个配置，试运行/生产 {live} 个"


def build_platform_readiness(configs):
    """Build a non-sensitive readiness response from already scoped configs."""
    grouped = defaultdict(list)
    for config in configs:
        grouped[str(config.platform or "").lower()].append(config)

    security_ready = bool(getattr(settings, "LIVE_PLATFORM_SECURITY_APPROVED", False))
    custody_ready = approved_custody_configured()
    network_ready = (
        live_network_mode_enabled()
        and bool(getattr(settings, "LIVE_PLATFORM_ALLOWED_HOSTS", []) or [])
        and not bool(getattr(settings, "DEBUG", False))
    )
    items = []
    for platform, label in MARKETPLACE_PLATFORMS:
        platform_configs = grouped.get(platform, [])
        evaluated = [
            (config, integration_config_oauth_blockers(platform, config))
            for config in platform_configs
        ]
        ready_configs = [config for config, blockers in evaluated if not blockers]
        if evaluated:
            _best_config, blockers = min(evaluated, key=lambda entry: len(entry[1]))
        else:
            blockers = ["config_missing"]
        has_sandbox = any(config.environment in {"mock", "sandbox"} for config in platform_configs)
        items.append(
            {
                "platform": label,
                "platform_code": platform,
                "current_access_status": "read_only_ready" if ready_configs else "blocked",
                "current_access_status_label": "只读接入就绪" if ready_configs else "暂不可接入",
                "mock_sandbox_status": "sandbox_configured" if has_sandbox else "not_configured",
                "mock_sandbox_status_label": "已配置测试环境" if has_sandbox else "未配置测试环境",
                "production_status": "production_readonly_ready" if ready_configs else "production_disabled",
                "production_status_label": "生产只读就绪" if ready_configs else "生产接入关闭",
                "config_summary": _config_summary(platform_configs),
                "blocker_codes": blockers,
                "blocker_summary": "；".join(BLOCKER_LABELS.get(code, code) for code in blockers),
                "security_review_done": security_ready,
                "credential_custody_done": custody_ready,
                "network_isolation_done": network_ready,
                "high_risk_action_allowed": False,
            }
        )

    return {
        "api_status": "connected",
        "mode": "production_readonly",
        "production_write_enabled": False,
        "global_gates": {
            "security_review_done": security_ready,
            "credential_custody_done": custody_ready,
            "network_isolation_done": network_ready,
        },
        "items": items,
    }
