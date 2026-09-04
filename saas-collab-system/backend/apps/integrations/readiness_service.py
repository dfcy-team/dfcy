"""Read-only production readiness projection for marketplace integrations.

The projection intentionally reports facts already enforced by the OAuth/live
provider gates.  It never enables network access, approves a configuration, or
returns credential material.
"""

from collections import defaultdict

from django.conf import settings

from .capability import approved_custody_configured, live_network_mode_enabled
from .live_providers import integration_config_oauth_blockers
from .platform_schema_service import get_platform_schema
from .production_settings import get_runtime_setting


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
    "readonly_sync_feature_disabled": "生产只读同步功能未启用",
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
    "readonly_not_approved": "生产只读能力尚未审批",
}

READINESS_ACTION_LABELS = {
    "repair_contract": "修复合同版本",
    "approve_readonly": "审批生产只读",
    "revoke_readonly": "撤销只读审批",
}


def _expected_contract(config):
    """Return the currently approved contract for a marketplace config."""
    platform = str(getattr(config, "platform", "") or "").lower()
    if platform not in {"lazada", "shopee", "tiktok"}:
        return ""
    return str(
        get_platform_schema(platform, environment=getattr(config, "environment", None))["contract_versions"][0]
    )


def _readonly_state(config):
    """Return the persisted approval state, independent of transient global gates."""
    return bool(
        getattr(config, "network_enabled", False)
        and getattr(config, "sync_read_enabled", False)
        and not getattr(config, "sync_write_enabled", False)
    )


def _config_action(code, config, *, available, blocker_codes=()):
    path_by_code = {
        "repair_contract": f"/api/internal/integrations/readiness/configs/{config.id}/repair-contract/",
        "approve_readonly": f"/api/internal/integrations/readiness/configs/{config.id}/readonly-approval/",
        "revoke_readonly": f"/api/internal/integrations/readiness/configs/{config.id}/readonly-approval/",
    }
    blockers = list(dict.fromkeys(str(code) for code in blocker_codes if code))
    return {
        "code": code,
        "label": READINESS_ACTION_LABELS[code],
        "available": bool(available),
        "requires_confirmation": True,
        "method": "POST",
        "path": path_by_code[code],
        "blocker_codes": blockers,
        "disabled_reason": "；".join(BLOCKER_LABELS.get(item, item) for item in blockers),
    }


def _config_readiness(config):
    """Build a non-secret, actionable readiness row for one config."""
    provider_blockers = list(
        integration_config_oauth_blockers(
            str(getattr(config, "platform", "") or "").lower(),
            config,
        )
    )
    provider_blockers = list(dict.fromkeys(provider_blockers))
    if not bool(get_runtime_setting("network", "readonly_sync_enabled", default=False)):
        provider_blockers.append("readonly_sync_feature_disabled")
    provider_blockers = list(dict.fromkeys(provider_blockers))
    readonly_approved = _readonly_state(config)
    blocker_codes = list(provider_blockers)
    if not readonly_approved:
        blocker_codes.append("readonly_not_approved")
    blocker_codes = list(dict.fromkeys(blocker_codes))

    target_contract = _expected_contract(config)
    repair_available = bool(
        str(getattr(config, "platform", "") or "").lower() in {"lazada", "shopee", "tiktok"}
        and target_contract
        and str(getattr(config, "contract_version", "") or "") != target_contract
    )
    approval_blockers = [
        code
        for code in provider_blockers
        if code != "network_not_approved"
    ]
    approve_available = bool(
        str(getattr(config, "platform", "") or "").lower() in {"lazada", "shopee", "tiktok"}
        and not readonly_approved
        and not approval_blockers
    )
    revoke_available = bool(
        getattr(config, "network_enabled", False)
        or getattr(config, "sync_read_enabled", False)
    )
    actions = [
        _config_action(
            "repair_contract",
            config,
            available=repair_available,
            blocker_codes=() if repair_available else ("contract_not_approved",),
        ),
        _config_action(
            "approve_readonly",
            config,
            available=approve_available,
            blocker_codes=approval_blockers,
        ),
        _config_action(
            "revoke_readonly",
            config,
            available=revoke_available,
        ),
    ]
    return {
        "id": config.id,
        "account_alias": config.account_alias,
        "environment": config.environment,
        "status": config.status,
        "contract_version": config.contract_version,
        "callback_url": config.callback_url,
        "network_enabled": bool(config.network_enabled),
        "sync_read_enabled": bool(config.sync_read_enabled),
        "sync_write_enabled": bool(config.sync_write_enabled),
        "readonly_approved": readonly_approved,
        "config_version": config.config_version,
        "blocker_codes": blocker_codes,
        "blocker_summary": "；".join(BLOCKER_LABELS.get(code, code) for code in blocker_codes),
        "can_repair_contract": repair_available,
        "can_approve_readonly": approve_available,
        "actions": actions,
    }


def build_config_readiness(config):
    """Return the non-sensitive readiness projection for one configuration."""
    return _config_readiness(config)


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

    security_ready = bool(get_runtime_setting("network", "security_approved", default=False))
    custody_ready = approved_custody_configured()
    network_ready = (
        live_network_mode_enabled()
        and bool(get_runtime_setting("network", "allowed_hosts", default=[]))
        and not bool(getattr(settings, "DEBUG", False))
    )
    readonly_sync_ready = bool(get_runtime_setting("network", "readonly_sync_enabled", default=False))
    items = []
    for platform, label in MARKETPLACE_PLATFORMS:
        platform_configs = grouped.get(platform, [])
        config_rows = [_config_readiness(config) for config in platform_configs]
        evaluated = [
            (config, row["blocker_codes"])
            for config, row in zip(platform_configs, config_rows)
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
                "configs": config_rows,
                "blocker_codes": blockers,
                "blocker_summary": "；".join(BLOCKER_LABELS.get(code, code) for code in blockers),
                "security_review_done": security_ready,
                "credential_custody_done": custody_ready,
                "network_isolation_done": network_ready,
                "readonly_sync_enabled": readonly_sync_ready,
                "high_risk_action_allowed": False,
                "actions": {
                    code: {
                        "available": any(
                            action["code"] == code and action["available"]
                            for row in config_rows
                            for action in row["actions"]
                        ),
                        "config_ids": [
                            row["id"]
                            for row in config_rows
                            if any(
                                action["code"] == code and action["available"]
                                for action in row["actions"]
                            )
                        ],
                    }
                    for code in READINESS_ACTION_LABELS
                },
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
            "readonly_sync_enabled": readonly_sync_ready,
        },
        "items": items,
    }
