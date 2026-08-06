from django.db import migrations


CONTRACT_VERSION = "a2-sandbox-v1"


def register_initial_evidence(apps, schema_editor):
    """Register the honest current state of the six real Sandbox preparation items.

    Items without console/custody evidence stay `pending`; values are never guessed.
    """
    from apps.integrations.models import oauth_evidence_write

    Evidence = apps.get_model("integrations", "MarketplaceOAuthEvidence")

    endpoint_masked = {
        "authorization_entry": "",
        "token_exchange": "",
        "token_refresh": "",
        "token_revoke": "",
        "regional_domain": "",
        "api_version": "",
        "minimum_read_scopes": [],
        "token_ttl": "",
    }
    tiktok_endpoint_masked = dict(
        endpoint_masked,
        shop_info_endpoint_note=(
            "任务书必改项 5 列出 /authorization/202309/shops；"
            "精确路径须控制台复核后登记，不登记推测值。"
        ),
    )

    rows = []
    for platform in ("shopee", "tiktok"):
        rows.append(
            Evidence(
                evidence_key="a2_00_app_identity",
                platform=platform,
                environment="sandbox",
                readiness="pending",
                masked_value={
                    "app_id_mask": "",
                    "organization": "",
                    "environment": "sandbox",
                    "owner": "",
                },
                source="获批应用控制台未登记（开发账号交接文件仅含 VM/数据库账号，无平台应用标识）",
                confirmed_by="开发A",
                contract_version="",
            )
        )
        rows.append(
            Evidence(
                evidence_key="a2_00_endpoint_contract",
                platform=platform,
                environment="sandbox",
                readiness="pending",
                masked_value=tiktok_endpoint_masked if platform == "tiktok" else endpoint_masked,
                source="控制台与官方文档原文未复核；合同值不填推测值",
                confirmed_by="开发A",
                contract_version="",
            )
        )
        rows.append(
            Evidence(
                evidence_key="a2_00_callback_url",
                platform=platform,
                environment="sandbox",
                readiness="pending",
                masked_value={"callback_url": "", "console_registration_consistency": ""},
                source="HTTPS callback URL 未登记（禁通配符、IP、localhost）",
                confirmed_by="开发A",
                contract_version="",
            )
        )

    rows.append(
        Evidence(
            evidence_key="a2_00_custody_contract",
            platform="shared",
            environment="sandbox",
            readiness="pending",
            masked_value={
                "input_semantics": "授权 code 仅内存传递，禁止持久化/日志/异常/审计/重试队列",
                "output_fields": ["credential_id", "token_id", "mask", "version", "expires_at"],
                "hmac_scope": "HMAC-SHA256 请求签名只在托管侧计算",
                "rotation_semantics": "refresh 返回新版本引用，旧版本由托管侧作废",
                "provider": "",
                "endpoint_reference": "",
            },
            source="托管接口语义已由任务书固定；托管服务名称/端点/合同版本号未登记",
            confirmed_by="开发A",
            contract_version="",
        )
    )
    rows.append(
        Evidence(
            evidence_key="a2_00_network_egress",
            platform="shared",
            environment="sandbox",
            readiness="pending",
            masked_value={
                "double_gate": "MARKETPLACE_OAUTH_NETWORK_ENABLED + 环境/域名 allowlist",
                "egress": "仅 HTTPS 白名单 host",
                "dns_guard": "解析结果不得落入私网地址段",
                "timeout_seconds": {"connect": 5, "read": 15, "status": "默认值，最终以审批为准"},
                "allowlist_hosts": [],
                "emergency_stop": "关闭 MARKETPLACE_OAUTH_NETWORK_ENABLED 即全量 fail closed",
                "fallback": "回退 synthetic 并登记故障事件，保持旧授权不变",
            },
            source="设计已固定、代码门禁已就位；allowlist host 依赖控制台端点登记后派生",
            confirmed_by="开发A",
            contract_version=CONTRACT_VERSION,
        )
    )
    rows.append(
        Evidence(
            evidence_key="a2_00_security_confirmation",
            platform="shared",
            environment="sandbox",
            readiness="ready",
            masked_value={
                "scope": "Sandbox 阶段按 E1–E3 口径：控制台证据、托管接口、出口 allowlist + 急停开关；Pilot/Production 按完整六项口径",
                "handover_document": "developer_a_shopee_tiktok_handover.md (2026-08-06)",
                "technical_bottom_lines": [
                    "真实密码/Token/Secret/私钥不进 Git/日志",
                    "tenant/store 数据不互串",
                    "数据库变更前保留可恢复备份",
                ],
            },
            source="交接文件 developer_a_shopee_tiktok_handover.md (2026-08-06) §1/§2",
            confirmed_by="开发A",
            contract_version=CONTRACT_VERSION,
        )
    )

    with oauth_evidence_write():
        Evidence.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0014_marketplace_oauth_evidence"),
    ]

    operations = [
        migrations.RunPython(register_initial_evidence, migrations.RunPython.noop),
    ]
