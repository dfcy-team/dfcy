"""Opt-in daily policies. Only completed, same-source query bounds advance time."""
import hashlib
import json
from datetime import timedelta

from rest_framework.exceptions import ValidationError

from .models import SyncCheckpoint


def recommended_policy(job):
    platform = job.integration_config.platform
    values = {"strategy_profile": "efficient_v1", "execution_budget_seconds": 120}
    if job.resource_type == "sales_order":
        values.update(query_mode="incremental", collection_time_basis="updated",
                      incremental_anchor="checkpoint", lookback_days=1, overlap_minutes=5)
        notice = "按真实成功查询上界增量采集，重叠 5 分钟；首次无可信上界时回看今天。更早缺口须使用历史补采。"
    elif job.resource_type == "platform_product" and platform in {"shopee", "tiktok"}:
        values.update(product_full_sync=False, query_mode="incremental",
                      incremental_anchor="checkpoint", lookback_days=1, overlap_minutes=5)
        if platform == "shopee":
            values["product_order_backfill"] = "catalog_and_order_missing"
        notice = "首次按已验证平台状态完成商品目录初始化，之后按成功上界增量。Shopee 同时按订单缺失商品 ID 定向补齐，不猜测 SKU；不保证找回平台已删除的商品。"
    elif job.resource_type in {"refund_return", "settlement_bill"}:
        values.update(query_mode="incremental", incremental_anchor="lookback", lookback_days=7)
        notice = "退款和财务保留 7 天滚动复查与短分段，等待调度公平轮转；不假定平台账务具备可靠更新时间。更早数据仍用历史补采。"
    else:
        return {"available": False, "values": {}, "notice": "此资源保持现有策略，不自动推断平台增量契约。"}
    return {"available": True, "values": values, "notice": notice + " 不改变启停、执行方式、频率或权限。"}


def prepare_policy(job, values):
    if values.get("strategy_profile") == "efficient_v1":
        recommendation = recommended_policy(job)
        if not recommendation["available"]:
            raise ValidationError({"strategy_profile": "此资源尚无已验证的高效增量建议。"})
        return {**recommendation["values"], **values}
    return values


def _source_key(job):
    scope = job.sync_scope or {}
    query = (job.sync_scope or {}).get("query") or {}
    config = job.integration_config
    config_scope = (config.platform_config or {}).get("sync_scope") or {}
    authorization = job.store_authorization if job.store_authorization_id else None
    statuses = query.get("statuses", scope.get("statuses", scope.get("query_statuses", config_scope.get("statuses", config_scope.get("query_statuses")))))
    basis = query.get("time_basis", scope.get("time_basis", "created" if query.get("mode") == "range" else "updated"))
    # IDs and non-secret query controls only. Source changes invalidate old proof.
    payload = [job.tenant_id, job.integration_config_id, config.platform, config.environment,
               job.resource_type, job.store_authorization_id, job.warehouse_authorization_id,
               config.regions, statuses, basis,
               [authorization.store_id, authorization.region, authorization.platform_store_id] if authorization else None]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _successful_proof(job):
    checkpoint = SyncCheckpoint.objects.select_related("last_success_run").filter(
        tenant_id=job.tenant_id, sync_job_id=job.pk).first()
    run = checkpoint.last_success_run if checkpoint else None
    if not run or run.tenant_id != job.tenant_id or run.sync_job_id != job.pk:
        return None
    log = run.masked_log or {}
    proof = log.get("sync_policy") or {}
    decision = log.get("decision_source") or {}
    resolved = (log.get("runtime_budget") or {}).get("resolved_scope") or {}
    if (run.status != "success" or run.history_segment_id or run.failed_count
            or log.get("execution_mode") != "live_readonly"
            or proof.get("source_key") != _source_key(job)
            or decision.get("platform") != job.integration_config.platform
            or decision.get("resource_type") != job.resource_type
            or (job.resource_type == "sales_order" and resolved.get("time_basis") != "updated")
            or not decision.get("ended_without_cursor") or not decision.get("all_records_valid")):
        return None
    return log


def resolve_job_scope(job):
    from .readonly_clients import default_sync_scope
    frozen = getattr(job, "_frozen_sync_scope", None)
    if isinstance(frozen, dict):
        return dict(frozen)
    scope = dict(job.sync_scope or {})
    query = scope.get("query") or {}
    anchor = query.get("incremental_anchor", "lookback")
    platform = job.integration_config.platform
    product = job.resource_type == "platform_product"
    mode = query.get("mode", scope.get("query_mode", "incremental"))
    supported = job.resource_type == "sales_order" or (product and platform in {"shopee", "tiktok"})
    basis = query.get("time_basis", "created" if mode == "range" else "updated")
    if anchor == "checkpoint" and (not supported or mode != "incremental"
                                    or (job.resource_type == "sales_order" and basis != "updated")
                                    or (product and scope.get("product_full_sync", True))
                                    or query.get("product_order_backfill") == "order_missing_only"):
        raise ValidationError({"incremental_anchor": "成功上界仅用于更新时间增量订单或增量商品目录；全量、指定范围和仅缺失 ID 模式请使用回看。"})
    proof = _successful_proof(job) if supported else None
    initialized = bool(proof and (proof.get("sync_policy") or {}).get("product_catalog_initialized"))
    bootstrap = bool(product and scope.get("strategy_profile") == "efficient_v1" and not initialized
                     and query.get("product_order_backfill") != "order_missing_only")
    if bootstrap:
        scope["product_full_sync"] = True
    resolved = default_sync_scope(job.integration_config, scope, job.resource_type, job.store_authorization)
    notice = "保持现有回看范围。"
    effective_anchor = "lookback"
    if bootstrap:
        effective_anchor, notice = "bootstrap", "尚无同来源完整目录初始化成功证据，本次先采完整目录；成功后转为增量。"
    elif anchor == "checkpoint":
        upper = ((proof or {}).get("runtime_budget") or {}).get("resolved_scope", {}).get("time_to")
        if not isinstance(upper, int) or isinstance(upper, bool) or upper <= 0:
            notice = "没有可证明的同来源成功查询上界，回退到所选回看天数；更早缺口请历史补采。"
        else:
            overlap = int(query.get("overlap_minutes", 5))
            start = upper - overlap * 60
            end = resolved["time_to"]
            maximum = 30 if product else 31
            if start >= end or end - start > timedelta(days=maximum).total_seconds():
                raise ValidationError({"incremental_anchor": f"成功上界已超出单次 {maximum} 天范围或晚于当前时间；请先历史补采，或明确预览改为回看。未截断缺口。"})
            resolved["time_from"] = start
            effective_anchor, notice = "checkpoint", "从上一真实成功查询上界减去重叠窗口继续；不使用执行完成时间跳过期间数据。"
    resolved["_sync_policy"] = {
        "version": "efficient-sync-v1", "source_key": _source_key(job),
        "anchor": effective_anchor, "notice": notice, "bootstrap": bootstrap,
        "product_catalog_initialized": bool(product and (initialized or resolved["product_full_sync"])
                                            and resolved["product_order_backfill"] != "order_missing_only"),
    }
    return resolved
