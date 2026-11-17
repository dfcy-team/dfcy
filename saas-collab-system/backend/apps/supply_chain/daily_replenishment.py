from datetime import date
"""Daily, permission-scoped replenishment snapshots backed by existing job rows.

Wire ``generate_daily_replenishments`` to a 10:40 Asia/Shanghai scheduler and
``DailyLatest`` / ``DailyRows`` to read-only routes in the host application.
"""
from datetime import time, timedelta
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.commerce import country_decisions
from apps.permissions.models import OrgMembership
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management import operating as operating_domain
from apps.supply_chain import replenishment_jobs as jobs
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import ReplenishmentCalculationJob, ReplenishmentCalculationRow, ReplenishmentStrategy
from apps.supply_chain.services import request_hash, _tenant_lock
from apps.supply_chain.views import ReadAPI
from apps.supply_chain.permissions import MANAGE as SC_MANAGE, VIEW as SC_VIEW
from apps.commerce.supply_pipeline import SUMMARY_PERMISSION

from apps.supply_chain.replenishment_jobs import _serialize, _validated_config

TZ = ZoneInfo("Asia/Shanghai")
DAILY_TTL = timedelta(days=7)
MAX_JOBS_PER_RUN = 20
MAX_ATTEMPTS = 3
MAX_ERROR_COUNT = 20
SCOPE_CODES = (SC_VIEW, SC_MANAGE, operating_domain.VIEW, operating_domain.MANAGE,
               country_decisions.INVENTORY, country_decisions.SALES, SUMMARY_PERMISSION)
RESOURCE_CODES = {country_decisions.INVENTORY: "commerce.inventory",
                  country_decisions.SALES: "sales_management.sales",
                  SUMMARY_PERMISSION: "sales_management.supply_summary"}


def _scope_descriptor(actor):
    """Effective authorization description, deliberately independent of data changes."""
    cache = {}
    states = []
    for code in SCOPE_CODES:
        resource = RESOURCE_CODES.get(code)
        scopes = get_permission_data_scopes(actor, code, cache=cache, resource_code=resource) if resource else get_permission_data_scopes(actor, code, cache=cache)
        states.append({"code": code, "allowed": check_user_permission(actor, code, cache=cache),
                       "scopes": sorted([{"scope_type": s["scope_type"], "config": s.get("config") or {}}
                                         for s in scopes], key=request_hash)})
    # Include the domain's inventory/sales scope descriptor as a second guard.
    states.append({"code": "country_decisions", "signature": country_decisions.permission_signature(actor, permission_cache=cache)})
    all_scopes = all(s["allowed"] and s["scopes"] and
                     all(item["scope_type"] == "all" for item in s["scopes"])
                     for s in states if "allowed" in s)
    return states, all_scopes


def _effective_read_policy(actor, states, country_id):
    """Only read-affecting scopes define shared facts; legacy self/org scopes stay private."""
    by_code = {state['code']: state for state in states}
    policies = {}
    private = False
    keys = {country_decisions.INVENTORY: {'warehouse_ids','sku_ids','spu_ids','platforms','store_ids','regions'},
            country_decisions.SALES: {'platforms','store_ids','regions'}}
    for code, allowed_keys in keys.items():
        state = by_code.get(code, {})
        scopes = state.get('scopes') or []
        if state.get('allowed') and (getattr(actor, 'is_superuser', False) or any(x['scope_type']=='all' for x in scopes)):
            policies[code] = 'ALL'
            continue
        normalized = []
        if not state.get('allowed') or not scopes:
            private = True
        for scope in scopes:
            config = scope.get('config') or {}
            if scope['scope_type'] != 'custom' or not config or not set(config).issubset(allowed_keys):
                private = True
            normalized.append({'scope_type':scope['scope_type'], 'config':{
                k:sorted(v,key=str) if isinstance(v,list) else v for k,v in config.items()}})
        policies[code] = [entry for _,entry in sorted({request_hash(entry):entry for entry in normalized}.items())]
    pipeline = False
    for code in (SUMMARY_PERMISSION, SC_VIEW):
        state = by_code.get(code, {})
        if state.get('allowed') and (getattr(actor,'is_superuser',False) or any(
            scope['scope_type']=='all' or (scope['scope_type']=='custom' and country_id in (scope.get('config') or {}).get('site_ids',[]))
            for scope in state.get('scopes') or [])):
            pipeline = True
    return {'metrics':policies, 'pipeline_allowed':pipeline,
            'cost_link':bool(by_code.get(SC_VIEW,{}).get('allowed'))}, private


def daily_key(actor, country_id, strategy_id, strategy_version, *, analysis_mode="country", platform_type="", _scope_state=None):
    """Stable for a day's data refreshes; changes when its effective scope changes."""
    descriptor, all_scopes = _scope_state if _scope_state is not None else _scope_descriptor(actor)
    policy, private = _effective_read_policy(actor, descriptor, country_id)
    full_data = all_scopes or (all(policy['metrics'].get(code)=='ALL' for code in
        (country_decisions.INVENTORY,country_decisions.SALES)) and policy['pipeline_allowed'] and policy['cost_link'])
    identity = {"tenant": actor.tenant_id, "country": country_id, "strategy": strategy_id,
                "strategy_version": strategy_version,
                "permissions": 'full-country-metrics-v1' if full_data else {'read_policy_v2':policy}}
    if analysis_mode == "platform":
        identity.update(analysis_mode="platform", platform_type=platform_type.casefold(), algorithm="platform-own-sales-v1")
    if not full_data and private:
        identity.update(user=actor.pk, membership=getattr(actor, "_active_membership_id", None))
    return request_hash(identity)


def _within_schedule(now=None):
    local_now = (now or timezone.now()).astimezone(TZ)
    return local_now.time() >= time(10, 40)


def _membership_contexts(user, now):
    contexts = [None]
    memberships = OrgMembership.objects.filter(tenant_id=user.tenant_id, user_id=user.pk, status="active",
        department__status="active").filter(Q(valid_until__isnull=True) | Q(valid_until__gt=now)).values_list("pk", flat=True)
    contexts.extend(memberships)
    for membership_id in contexts:
        user._active_membership_id = membership_id
        yield membership_id
    if hasattr(user, "_active_membership_id"):
        delattr(user, "_active_membership_id")


def _daily_meta(job):
    meta = job.config.get("daily") or {}
    return meta if meta.get("key") and meta.get("day") else None


def _complete(job):
    return job.status == "completed" and job.processed == job.total


def _row_count(job):
    return ReplenishmentCalculationRow.objects.filter(job=job).count()


def _same_day_job(actor, country, strategy, key, day, *, analysis_mode="country", platform_type=""):
    parameters = {"analysis_mode": analysis_mode}
    if analysis_mode == "platform":
        parameters["platform_type"] = platform_type
    queryset = ReplenishmentCalculationJob.objects.filter(tenant_id=actor.tenant_id, country=country,
        strategy=strategy, strategy_version=strategy.version, config__daily__key=key,
        config__daily__day=day.isoformat())
    if analysis_mode == "platform":
        queryset = queryset.filter(config__parameters__analysis_mode="platform",
                                   config__parameters__platform_type=platform_type)
    return queryset.order_by("-created_at")


def _latest_complete(queryset, now):
    """Select the newest complete unexpired snapshot, allowing prior-day fallback."""
    candidates = queryset.filter(status="completed", processed=models_F("total"), expires_at__gt=now).order_by(
        "-business_date", "-created_at")
    for job in candidates:
        if _complete(job) and _row_count(job) == job.total:
            return job
    return None


def _promote_manual(actor, country, strategy, candidate_ids, config, signature, key, day):
    """Reuse an exact, complete same-day manual country run."""
    # Old platform jobs used country-wide sales with identical request parameters.
    # They cannot be promoted into the own-platform algorithm introduced here.
    if config.get("parameters", {}).get("analysis_mode") == "platform":
        return None
    manual = ReplenishmentCalculationJob.objects.filter(tenant_id=actor.tenant_id, requested_by=actor,
        country=country, strategy=strategy, strategy_version=strategy.version, business_date=day,
        permission_signature=signature, status="completed", processed__gte=0, total=len(candidate_ids),
        expires_at__gt=timezone.now(), candidate_ids=candidate_ids).exclude(config__daily__key__isnull=False).order_by("-created_at")
    for job in manual[:10]:
        if not _complete(job) or job.config.get("parameters") != config.get("parameters") or _row_count(job) != job.total:
            continue
        updated_config = {**job.config, "daily": {"key": key, "day": day.isoformat(), "attempt": 1,
            "promoted_from_manual": True, "calculated_at": job.updated_at.isoformat()}}
        ReplenishmentCalculationJob.objects.filter(pk=job.pk, status="completed", processed=job.total).update(
            config=updated_config, expires_at=timezone.now() + DAILY_TTL)
        job.refresh_from_db()
        return job
    return None


def _enqueue_daily(actor, country, strategy, candidate_ids, config, signature, key, day, now):
    # Serialize cross-worker creation; a success/pending run wins over a retry.
    with transaction.atomic():
        _tenant_lock(actor)
        jobs_for_key = _same_day_job(actor, country, strategy, key, day)
        stale_ids = list(jobs_for_key.filter(status__in=["queued", "running"], hard_deadline__lte=now)
                         .values_list("pk", flat=True))
        if stale_ids:
            ReplenishmentCalculationJob.objects.filter(pk__in=stale_ids,
                status__in=["queued", "running"]).update(status="failed", error="每日补货后台任务超时，等待下轮重试。",
                    lease_token=None, lease_expires_at=None, updated_at=now)
        active = jobs_for_key.filter(status__in=["queued", "running"], hard_deadline__gt=now).first()
        if active:
            return active
        ready = jobs_for_key.filter(status="completed", processed=models_F("total")).first()
        if ready and ready.expires_at > now and _row_count(ready) == ready.total:
            return ready
        promoted = _promote_manual(actor, country, strategy, candidate_ids, config, signature, key, day)
        if promoted:
            return promoted
        attempts = [int((_daily_meta(SimpleNamespace(config=value)) or {}).get("attempt", 0))
                    for value in jobs_for_key.values_list("config", flat=True)]
        attempt = max(attempts, default=0) + 1
        if attempt > MAX_ATTEMPTS:
            return None
        active_tenant = ReplenishmentCalculationJob.objects.filter(tenant_id=actor.tenant_id,
            status__in=["queued", "running"], hard_deadline__gt=now)
        _, actor_private = _effective_read_policy(actor, _scope_descriptor(actor)[0], country.pk)
        if active_tenant.count() >= 10 or (actor_private and active_tenant.filter(requested_by=actor).count() >= 2):
            return None
        daily_config = {**config, "daily": {"key": key, "day": day.isoformat(), "attempt": attempt}}
        job = ReplenishmentCalculationJob.objects.create(tenant_id=actor.tenant_id, requested_by=actor,
            country=country, strategy=strategy, strategy_version=strategy.version, business_date=day,
            config=daily_config, candidate_ids=candidate_ids, permission_signature=signature,
            status="queued", total=len(candidate_ids), processed=0, next_offset=0,
            counts={"positive": 0, "zero": 0, "unknown": 0, "awaiting_procurement": 0, "arrival_gap": 0},
            expires_at=now + DAILY_TTL, hard_deadline=now + timedelta(hours=2))
        transaction.on_commit(lambda: jobs._enqueue(job.pk))
        return job


def models_F(field):
    # Kept as a small helper to avoid importing models expressions at module import.
    from django.db.models import F
    return F(field)


def generate_daily_replenishments(*, now=None, limit=MAX_JOBS_PER_RUN, business_day=None):
    """Queue missing daily standard-country snapshots; intended for 10:40 scheduler only."""
    now = now or timezone.now()
    day = date.fromisoformat(business_day) if isinstance(business_day, str) else (business_day or business_date())
    if (business_date() - day).days not in (0, 1):
        raise ValueError("Only current or previous business day may run")
    if day == business_date() and not _within_schedule(now):
        return {"queued": 0, "reused": 0, "skipped": 0, "reason": "before_10_40"}
    actor_model = get_user_model()
    users = actor_model.objects.filter(is_active=True, user_type="internal").order_by("tenant_id", "pk")
    queued = reused = skipped = errors = pending = failed_dimensions = 0
    seen = set()
    cap = max(1, min(int(limit), MAX_JOBS_PER_RUN))
    for user in users.iterator():
        for membership_id in _membership_contexts(user, now):
            try:
                country_rows = country_decisions.countries_for(user).filter(pk__in=ReplenishmentStrategy.objects.filter(tenant_id=user.tenant_id, active=True).values('country_id')).filter(pk__in=ReplenishmentStrategy.objects.filter(tenant_id=user.tenant_id,active=True).values("country_id"))
                scope_state = _scope_descriptor(user)
            except (PermissionDenied, NotFound):
                skipped += 1
                continue
            except Exception:
                skipped += 1
                errors = min(errors + 1, MAX_ERROR_COUNT)
                pending += 1
                continue
            try:
                for country in country_rows.iterator():
                    try:
                        from apps.supply_chain.replenishment import _country
                        try:
                            _country(user, country.pk)
                        except (PermissionDenied, NotFound):
                            skipped += 1
                            continue
                        strategy = ReplenishmentStrategy.objects.filter(tenant_id=user.tenant_id, country=country, active=True).order_by("-version", "pk").first()
                        if not strategy:
                            skipped += 1
                            continue
                        platform_options = country_decisions.sales_platform_options(user, country)
                        dimensions = [("country", "")] + [("platform", row["platform_type"]) for row in platform_options]
                        for analysis_mode, platform_type in dimensions:
                            key = daily_key(user, country.pk, strategy.pk, strategy.version,
                                            analysis_mode=analysis_mode, platform_type=platform_type, _scope_state=scope_state)
                            unique = (user.tenant_id, country.pk, strategy.pk, key, day)
                            if unique in seen:
                                continue
                            seen.add(unique)
                            qs = _same_day_job(user, country, strategy, key, day,
                                               analysis_mode=analysis_mode, platform_type=platform_type)
                            complete = qs.filter(status="completed", processed=models_F("total"), expires_at__gt=now).first()
                            if complete and _row_count(complete) == complete.total:
                                reused += 1
                                continue
                            active = qs.filter(status__in=["queued", "running"], hard_deadline__gt=now).first()
                            if active:
                                queued += 1
                                continue
                            attempts = [int((_daily_meta(SimpleNamespace(config=value)) or {}).get("attempt", 0))
                                        for value in qs.values_list("config", flat=True)]
                            if max(attempts, default=0) >= MAX_ATTEMPTS:
                                skipped += 1
                                failed_dimensions += 1
                                continue
                            payload = {"country_id": country.pk, "source_kind": "cycle", "analysis_mode": analysis_mode, "sales_end": (day - timedelta(days=1)).isoformat()}
                            if analysis_mode == "platform": payload["platform_type"] = platform_type
                            validated_country, validated_strategy, candidate_ids, values, config = _validated_config(user, payload)
                            signature = jobs._scope_signature(user, business_day=day)
                            result = _enqueue_daily(user, validated_country, validated_strategy, candidate_ids, config,
                                                    signature, key, day, now)
                            if result:
                                if _complete(result): reused += 1
                                else: queued += 1
                            else:
                                skipped += 1
                                pending += 1
                            if queued >= cap:
                                return {"queued": queued, "reused": reused, "skipped": skipped,
                                        "errors": errors, "pending": pending, "failed_dimensions": failed_dimensions, "expected_keys": sorted({k[3] for k in seen}), "has_more": True}
                    except Exception:
                        # Continue with the next authorized country; never return error text or IDs.
                        skipped += 1
                        errors = min(errors + 1, MAX_ERROR_COUNT)
                        pending += 1
            except Exception:
                skipped += 1
                errors = min(errors + 1, MAX_ERROR_COUNT)
                pending += 1
            finally:
                if hasattr(user, "_active_membership_id"):
                    delattr(user, "_active_membership_id")
    return {"queued": queued, "reused": reused, "skipped": skipped, "errors": errors, "pending": pending, "failed_dimensions": failed_dimensions, "expected_keys": sorted({k[3] for k in seen}), "has_more": False}


def _authorized_daily_target(actor, country_id, strategy_id=None, *, analysis_mode="country", platform_type=""):
    from apps.supply_chain.replenishment import _country
    if not country_id:
        raise ValidationError({"country_id": "请选择国家。"})
    country = _country(actor, country_id)
    country_decisions.require_metrics(actor)
    strategies = ReplenishmentStrategy.objects.filter(tenant_id=actor.tenant_id, country=country, active=True)
    strategy = strategies.filter(pk=strategy_id).first() if strategy_id else strategies.order_by("-version", "pk").first()
    if not strategy:
        raise NotFound("国家没有可用的补货策略。")
    if analysis_mode not in {"country", "platform"}:
        raise ValidationError({"analysis_mode": "每日建议仅支持国家或平台维度。"})
    normalized_platform = ""
    if analysis_mode == "platform":
        selected = str(platform_type or "").strip()
        options = country_decisions.sales_platform_options(actor, country)
        match = next((r["platform_type"] for r in options if r["platform_type"].casefold() == selected.casefold()), None)
        if not match:
            raise NotFound("平台不存在或不在当前账号授权范围内。")
        normalized_platform = match
    return country, strategy, daily_key(actor, country.pk, strategy.pk, strategy.version,
        analysis_mode=analysis_mode, platform_type=normalized_platform)


def _serialize_daily(job, refresh_status="已完成"):
    data = _serialize(job)
    meta = _daily_meta(job) or {}
    data["updated_at"] = meta.get("calculated_at") or job.updated_at.isoformat()
    data["calculated_at"] = data["updated_at"]
    data["daily_refresh_status"] = refresh_status
    data["revalidation_note"] = (f"每日北京时间10:40自动更新；本结果业务日期：{job.business_date.isoformat()}；"
                                  f"生成时间：{data['calculated_at']}；后台更新状态：{refresh_status}。"
                                  "建议在提交采购前按SKU复核实时数据。")
    return data


def daily_job_for_actor(actor, pk):
    """Authorize a completed daily job for detail endpoints and DailyRows."""
    try:
        job_id = uuid.UUID(str(pk))
    except (TypeError, ValueError):
        raise NotFound("每日补货参考不存在或已过期。")
    job = ReplenishmentCalculationJob.objects.filter(pk=job_id, tenant_id=actor.tenant_id,
        config__daily__key__isnull=False, status="completed", processed=models_F("total"),
        expires_at__gt=timezone.now()).select_related("country", "strategy").first()
    if not job:
        raise NotFound("每日补货参考不存在或已过期。")
    if not job.strategy.active or job.strategy.version != job.strategy_version:
        raise NotFound("每日补货参考对应的策略已变化。")
    params = job.config.get("parameters") or {}
    mode = params.get("analysis_mode", "country")
    platform = params.get("platform_type", "")
    _, _, current_key = _authorized_daily_target(actor, job.country_id, job.strategy_id,
        analysis_mode=mode, platform_type=platform)
    meta = _daily_meta(job)
    if not meta or meta["key"] != current_key or _row_count(job) != job.total:
        raise NotFound("每日补货参考不存在、授权范围已变化或已过期。")
    return job


class DailyLatest(ReadAPI):
    """Read-only latest complete snapshot. Never creates or modifies a calculation job."""
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        mode = request.query_params.get("analysis_mode", "country")
        platform_input = request.query_params.get("platform_type", "")
        country, strategy, key = _authorized_daily_target(request.user,
            request.query_params.get("country_id"), request.query_params.get("strategy_id"),
            analysis_mode=mode, platform_type=platform_input)
        normalized_platform = ""
        if mode == "platform":
            normalized_platform = next(r["platform_type"] for r in country_decisions.sales_platform_options(request.user, country)
                if r["platform_type"].casefold() == str(platform_input).strip().casefold())
        now = timezone.now()
        base = ReplenishmentCalculationJob.objects.filter(tenant_id=request.user.tenant_id,
            country=country, strategy=strategy, strategy_version=strategy.version,
            config__daily__key=key)
        if mode == "platform":
            base = base.filter(config__parameters__platform_type=normalized_platform)
        job = _latest_complete(base, now)
        if not job:
            raise NotFound("暂无已完成的每日补货参考，请等待10:40自动生成后再查看。")
        active_refresh = base.filter(status__in=["queued", "running"], hard_deadline__gt=now).order_by("-created_at").first()
        today = business_date()
        today_jobs = base.filter(config__daily__day=today.isoformat()).order_by("-created_at")
        failed_today = today_jobs.filter(status__in=["failed", "expired"]).first()
        if active_refresh:
            refresh_status = active_refresh.status
        elif job.business_date == today:
            refresh_status = "已完成"
        elif failed_today:
            refresh_status = "当日生成失败，继续显示上次结果"
        elif not _within_schedule(now):
            refresh_status = "等待今日10:40更新"
        else:
            attempts = [int((_daily_meta(SimpleNamespace(config=value)) or {}).get("attempt", 0))
                        for value in today_jobs.values_list("config", flat=True)]
            refresh_status = "当日重试次数已达上限，继续显示上次结果" if max(attempts, default=0) >= MAX_ATTEMPTS else "等待后台更新"
        serialized = _serialize_daily(job, refresh_status)
        serialized["id"] = f"daily:{job.pk}"
        serialized["country_id"] = country.pk
        serialized["strategy_id"] = strategy.pk
        serialized["analysis_mode"] = mode
        serialized["platform_type"] = normalized_platform
        serialized["recommendation_notice"] = ("按该平台自身销量计算；库存为国家共享库存参考，各平台建议量不可直接相加。"
            if mode == "platform" else "按国家整体销量与库存计算。")
        return Response({"data": serialized})


class DailyRows(jobs.ReplenishmentJobRows):
    """Daily snapshot row reader; bypasses owner-only manual job lookup, never mutates."""
    http_method_names = ["get", "head", "options"]

    def get_job(self, request, pk):
        return daily_job_for_actor(request.user, pk)

    def get(self, request, pk):
        # Restrict rows to both the original candidate set and today's visible SKU scope.
        job = self.get_job(request, pk)
        visible_ids = country_decisions.skus_for(request.user, job.country).values_list("pk", flat=True)
        from django.db.models import Q
        try:
            limit = int(request.query_params.get("limit", 20)); offset = int(request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            raise ValidationError("分页参数无效。")
        if not 1 <= limit <= 20 or offset < 0:
            raise ValidationError("每页最多20条，offset须为非负数。")
        quantity_filter = request.query_params.get("quantity_filter", "positive")
        if quantity_filter not in {"positive", "all", "zero", "unknown"}:
            raise ValidationError({"quantity_filter": "筛选值无效。"})
        qs = ReplenishmentCalculationRow.objects.filter(job=job, sku_id__in=job.candidate_ids).filter(sku_id__in=visible_ids)
        if quantity_filter == "positive": qs = qs.filter(suggested_quantity__gt=0)
        elif quantity_filter == "zero": qs = qs.filter(suggested_quantity=0)
        elif quantity_filter == "unknown": qs = qs.filter(suggested_quantity__isnull=True)
        risk = request.query_params.get("risk_filter", "").strip()
        if risk and risk not in {"awaiting_procurement", "arrival_gap", "data_check", "new_or_zero_sales", "out_of_stock", "replenish", "normal", "manual_review"}:
            raise ValidationError({"risk_filter": "风险筛选值无效。"})
        if risk == "awaiting_procurement": qs = qs.filter(has_submitted_demand=True)
        elif risk: qs = qs.filter(risk_level=risk)
        term = request.query_params.get("search", "").strip()
        if term: qs = qs.filter(Q(sku_code__icontains=term) | Q(legacy_sku_code__icontains=term) | Q(product_name__icontains=term))
        count = qs.count()
        rows = [row.payload for row in qs.order_by("sku_code", "sku_id")[offset:offset + limit]]
        return Response({"data": {"status": job.status, "rows": rows, "count": count,
            "total": job.total, "processed": job.processed, "counts": job.counts,
            "limit": limit, "offset": offset, "has_more": offset + len(rows) < count,
            "quantity_filter": quantity_filter, "id": f"daily:{job.pk}"}})
