"""Permission-isolated, chunked whole-country replenishment references."""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import uuid
from types import SimpleNamespace

from celery import current_app
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.response import Response

from apps.commerce import country_decisions
from apps.permissions.models import DataScope, OrgMembership
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management import operating as operating_domain
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import (ReplenishmentCalculationJob,
    ReplenishmentCalculationRow, ReplenishmentStrategy)
from apps.supply_chain.permissions import MANAGE as SC_MANAGE, VIEW as SC_VIEW
from apps.supply_chain.services import request_hash, _tenant_lock
from apps.commerce.supply_pipeline import SUMMARY_PERMISSION
from apps.supply_chain.views import ReadAPI
from apps.masterdata.models import CountrySiteMaster

CHUNK_SIZE = 20
MAX_CANDIDATES = 100_000
JOB_TTL = timedelta(minutes=15)
JOB_DEADLINE = timedelta(hours=2)
LEASE_DURATION = timedelta(minutes=3)
SCOPE_CODES = (SC_VIEW, SC_MANAGE, operating_domain.VIEW, operating_domain.MANAGE,
               country_decisions.INVENTORY, country_decisions.SALES, SUMMARY_PERMISSION)
RESOURCE_CODES = {country_decisions.INVENTORY: "commerce.inventory",
                  country_decisions.SALES: "sales_management.sales",
                  SUMMARY_PERMISSION: "sales_management.supply_summary"}


def _scope_signature(actor):
    # Reuse permission lookups only while producing this one signature. Never
    # carry this cache across requests or worker chunks, so revocations remain visible.
    cache = {}
    states = []
    for code in SCOPE_CODES:
        resource = RESOURCE_CODES.get(code)
        scopes = get_permission_data_scopes(actor, code, cache=cache, resource_code=resource) if resource else get_permission_data_scopes(actor, code, cache=cache)
        states.append({"code": code, "allowed": check_user_permission(actor, code, cache=cache),
            "scopes": sorted([{"scope_type": s["scope_type"], "config": s.get("config") or {}} for s in scopes],
                             key=lambda s: request_hash(s))})
    return request_hash({"tenant": actor.tenant_id, "user": actor.pk,
        "membership": getattr(actor, "_active_membership_id", None), "business_date": business_date(),
        "permissions": states, "metrics": country_decisions.permission_signature(actor, permission_cache=cache)})


def _restore_actor(job):
    actor = job.requested_by
    actor.refresh_from_db()
    if not actor.is_active or actor.user_type != "internal" or actor.tenant_id != job.tenant_id:
        raise PermissionDenied("账号或租户上下文已变化，请重新生成清单。")
    membership_id = job.config.get("membership_id")
    if membership_id is not None:
        valid = OrgMembership.objects.filter(pk=membership_id, user_id=actor.pk, tenant_id=job.tenant_id,
            status="active", department__status="active").filter(
            Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now())).exists()
        if not valid:
            raise PermissionDenied("组织成员授权已变化，请重新生成清单。")
        actor._active_membership_id = membership_id
    return actor


def _assert_actor_context(actor, job):
    if actor.tenant_id != job.tenant_id or actor.pk != job.requested_by_id:
        raise NotFound("补货计算任务不存在。")
    if getattr(actor, "_active_membership_id", None) != job.config.get("membership_id"):
        raise PermissionDenied("组织成员上下文已变化，请重新生成清单。")


def _serialize(job):
    status = job.status
    now = timezone.now()
    if status == "completed" and job.expires_at <= now:
        status = "expired"
    elif status in {"queued", "running"} and job.hard_deadline <= now:
        status = "expired"
    return {"id": str(job.pk), "status": status, "total": job.total, "processed": job.processed,
        "counts": job.counts, "error": job.error, "expires_at": job.expires_at.isoformat(),
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "strategy_version": job.strategy_version,
        "formula": "ceil(max(0, T - I - P - O - Q))；T按日销量预测及活动系数逐日累加，P按ETA日期计入；缺数据则待核对。",
        "revalidation_note": "全量清单按20个SKU分批读取，观察期间数据可能变化；转入运营订货草稿后仍须按SKU重新核对。",
        "platform_options": job.config.get("platform_options", []),
        "parameters": job.config.get("parameters", {})}


def _enqueue(job_id):
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        raise RuntimeError("补货计算队列处于同步执行模式，已拒绝在请求内执行。")
    current_app.send_task("apps.supply_chain.tasks.run_replenishment_calculation", args=[str(job_id)], retry=False)


def _validated_config(actor, payload):
    from apps.supply_chain.replenishment import ReferenceInput, _country, _strategy_json
    from apps.supply_chain.api import validated
    request = SimpleNamespace(data=payload)
    values = validated(ReferenceInput, request)
    country = _country(actor, values["country_id"])
    country_decisions.require_metrics(actor)
    strategy = ReplenishmentStrategy.objects.filter(tenant_id=actor.tenant_id, country=country, active=True).first()
    if values.get("strategy_id"):
        strategy = ReplenishmentStrategy.objects.filter(pk=values["strategy_id"], tenant_id=actor.tenant_id,
            country=country, active=True).first()
    if not strategy:
        raise ValidationError("此国家尚未保存有效补货策略，请先保存参数。")
    sales_end = values.get("sales_end") or (business_date() - timedelta(days=1))
    if sales_end >= business_date():
        raise ValidationError("销量统计截止日须为已完成日期。")
    start, end = values.get("activity_start"), values.get("activity_end")
    if start and end < business_date():
        raise ValidationError("活动日期已结束，请选择当前或未来活动日期。")
    if values.get("source_kind") == "season" and not start:
        raise ValidationError("季节订货必须填写活动开始和结束日期。")
    if values.get("exclude_operating_order_id"):
        from apps.sales_management.operating import order_for
        order = order_for(actor, values["exclude_operating_order_id"])
        if order.status != "draft" or order.country_id != country.pk:
            raise ValidationError("仅能排除本国家运营订货草稿的预留量。")
    platform_options = country_decisions.sales_platform_options(actor, country)
    selected = values["platform_type"].strip()
    if values["analysis_mode"] == "platform":
        matches = [r["platform_type"] for r in platform_options if r["platform_type"].casefold() == selected.casefold()]
        if not matches:
            raise ValidationError({"platform_type": "所选平台不在当前国家授权店铺范围内。"})
        selected = matches[0]
    candidates = country_decisions.skus_for(actor, country).filter(is_active=True,
        spu__product_type="standard").exclude(inventory_type="virtual").order_by("sku_code", "pk")
    ids = list(candidates.values_list("pk", flat=True)[:MAX_CANDIDATES + 1])
    if len(ids) > MAX_CANDIDATES:
        raise ValidationError("当前国家普通商品超过全量计算上限100000，请缩小范围或分批处理。")
    if values.get("source_kind") == "season" and not start:
        raise ValidationError("季节订货必须填写活动日期。")
    config = {"parameters": {**_strategy_json(strategy), "source_kind": values["source_kind"],
            "sales_end": sales_end.isoformat(), "activity_start": start.isoformat() if start else None,
            "activity_end": end.isoformat() if end else None, "activity_factor": str(values["activity_factor"]),
            "analysis_mode": values["analysis_mode"], "platform_type": selected,
            "exclude_operating_order_id": values.get("exclude_operating_order_id")},
        "membership_id": getattr(actor, "_active_membership_id", None),
        "platform_options": platform_options}
    return country, strategy, ids, values, config


class ReplenishmentJobs(ReadAPI):
    def post(self, request):
        actor = request.user
        country, strategy, candidate_ids, values, config = _validated_config(actor, request.data)
        signature = _scope_signature(actor)
        fingerprint = request_hash({"tenant": actor.tenant_id, "actor": actor.pk, "membership": config["membership_id"],
            "country": country.pk, "strategy": strategy.pk, "version": strategy.version,
            "business_date": business_date(), "candidate_ids": candidate_ids, "config": config})
        now = timezone.now()
        with transaction.atomic():
            _tenant_lock(actor)
            existing = ReplenishmentCalculationJob.objects.filter(tenant_id=actor.tenant_id,
                requested_by=actor, status__in=["queued", "running", "completed"], expires_at__gt=now,
                permission_signature=signature, config__fingerprint=fingerprint).filter(
                    Q(status__in=["queued", "running"]) | Q(created_at__gte=now - timedelta(seconds=60))
                ).order_by("-created_at").first()
            if existing and existing.config.get("fingerprint") == fingerprint:
                return Response({"data": _serialize(existing)}, status=202)
            active = ReplenishmentCalculationJob.objects.filter(tenant_id=actor.tenant_id,
                status__in=["queued", "running"], hard_deadline__gt=now)
            if active.filter(requested_by=actor).count() >= 2 or active.count() >= 10:
                raise Throttled("补货计算任务较多，请等待已有任务完成或取消后重试。")
            job = ReplenishmentCalculationJob.objects.create(tenant_id=actor.tenant_id,
                requested_by=actor, country=country, strategy=strategy, strategy_version=strategy.version,
                business_date=business_date(), config={**config, "fingerprint": fingerprint}, candidate_ids=candidate_ids,
                permission_signature=signature, total=len(candidate_ids), counts={"positive": 0, "zero": 0, "unknown": 0,
                    "awaiting_procurement": 0, "arrival_gap": 0},
                expires_at=now + JOB_DEADLINE, hard_deadline=now + JOB_DEADLINE)
            transaction.on_commit(lambda: self._dispatch(job.pk))
        job.refresh_from_db()
        return Response({"data": _serialize(job)}, status=202)

    @staticmethod
    def _dispatch(job_id):
        try:
            _enqueue(job_id)
        except Exception:
            ReplenishmentCalculationJob.objects.filter(pk=job_id, status="queued").update(
                status="failed", error="补货计算队列暂不可用，请稍后重试。")


class ReplenishmentJobDetail(ReadAPI):
    def get_job(self, request, pk):
        job = get_object_or_404(ReplenishmentCalculationJob.objects.select_related("requested_by", "strategy"),
            pk=pk, tenant_id=request.user.tenant_id, requested_by_id=request.user.pk)
        _assert_actor_context(request.user, job)
        now = timezone.now()
        if ((job.status == "completed" and job.expires_at <= now) or
                (job.status in {"queued", "running"} and job.hard_deadline <= now)):
            ReplenishmentCalculationJob.objects.filter(pk=job.pk).exclude(status="expired").update(status="expired")
            job.refresh_from_db()
        if job.status not in {"cancelled", "failed", "expired"}:
            try:
                _restore_actor(job)
                if (_scope_signature(request.user) != job.permission_signature or
                        job.strategy.version != job.strategy_version or not job.strategy.active):
                    raise PermissionDenied("权限范围或补货策略已变化，请重新生成清单。")
                if job.business_date != business_date():
                    raise ValidationError("业务日期已变化，请重新生成清单。")
            except Exception:
                ReplenishmentCalculationJob.objects.filter(pk=job.pk, status__in=["queued", "running", "completed"]).update(
                    status="failed", error="授权或策略已变化，请重新生成清单。")
                job.refresh_from_db()
        return job

    def get(self, request, pk):
        return Response({"data": _serialize(self.get_job(request, pk))})

    def delete(self, request, pk):
        job = self.get_job(request, pk)
        ReplenishmentCalculationJob.objects.filter(pk=job.pk, status__in=["queued", "running"]).update(
            status="cancelled", lease_token=None, lease_expires_at=None)
        job.refresh_from_db()
        return Response({"data": _serialize(job)})


class ReplenishmentJobRows(ReplenishmentJobDetail):
    def get(self, request, pk):
        job = self.get_job(request, pk)
        if job.status != "completed":
            return Response({"data": {"status": job.status, "rows": [], "count": 0, "limit": 20, "offset": 0}})
        try:
            limit = int(request.query_params.get("limit", 20)); offset = int(request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            raise ValidationError("分页参数无效。")
        if not 1 <= limit <= 20 or offset < 0:
            raise ValidationError("每页最多20条，offset须为非负数。")
        quantity_filter = request.query_params.get("quantity_filter", "positive")
        if quantity_filter not in {"positive", "all", "zero", "unknown"}:
            raise ValidationError({"quantity_filter": "筛选值无效。"})
        qs = ReplenishmentCalculationRow.objects.filter(job=job)
        if quantity_filter == "positive": qs = qs.filter(suggested_quantity__gt=0)
        elif quantity_filter == "zero": qs = qs.filter(suggested_quantity=0)
        elif quantity_filter == "unknown": qs = qs.filter(suggested_quantity__isnull=True)
        risk = request.query_params.get("risk_filter", "").strip()
        if risk and risk not in {"awaiting_procurement", "arrival_gap", "data_check", "new_or_zero_sales",
                "out_of_stock", "replenish", "normal", "manual_review"}:
            raise ValidationError({"risk_filter": "风险筛选值无效。"})
        if risk == "awaiting_procurement": qs = qs.filter(has_submitted_demand=True)
        elif risk: qs = qs.filter(risk_level=risk)
        term = request.query_params.get("search", "").strip()
        if term:
            qs = qs.filter(Q(sku_code__icontains=term) | Q(legacy_sku_code__icontains=term) | Q(product_name__icontains=term))
        count = qs.count()
        rows = [r.payload for r in qs.order_by("sku_code", "sku_id")[offset:offset + limit]]
        return Response({"data": {"status": job.status, "rows": rows, "count": count,
            "total": job.total, "processed": job.processed, "counts": job.counts,
            "limit": limit, "offset": offset, "has_more": offset + len(rows) < count,
            "quantity_filter": quantity_filter}})


def _active_job(job, token):
    job.refresh_from_db()
    if (job.status != "running" or job.lease_token != token or job.hard_deadline <= timezone.now() or
        job.business_date != business_date()):
        raise RuntimeError("补货计算任务已取消、过期或失去处理租约。")


def run_replenishment_calculation(job_id):
    now = timezone.now(); token = uuid.uuid4()
    claimed = ReplenishmentCalculationJob.objects.filter(pk=job_id, status__in=["queued", "running"],
        hard_deadline__gt=now).filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)).update(
            status="running", lease_token=token, lease_expires_at=now + LEASE_DURATION, updated_at=now)
    if not claimed:
        return
    job = ReplenishmentCalculationJob.objects.select_related("requested_by", "country", "strategy", "tenant").get(pk=job_id)
    try:
        actor = _restore_actor(job)
        if _scope_signature(actor) != job.permission_signature:
            raise PermissionDenied("授权范围已变化。")
        if not ReplenishmentStrategy.objects.filter(pk=job.strategy_id, tenant_id=job.tenant_id,
                version=job.strategy_version, active=True).exists():
            raise ValidationError("补货策略已变化或停用。")
        if job.business_date != business_date():
            raise ValidationError("业务日期已变化。")
        offset = job.next_offset
        ids = job.candidate_ids[offset:offset + CHUNK_SIZE]
        if not ids:
            with transaction.atomic():
                _active_job(job, token)
                ReplenishmentCalculationJob.objects.filter(pk=job.pk, lease_token=token).update(
                    status="completed", expires_at=timezone.now() + JOB_TTL, lease_token=None,
                    lease_expires_at=None, updated_at=timezone.now())
            return
        params = job.config["parameters"]
        chunk_payload = {"country_id": job.country_id,
            "strategy_id": job.strategy_id, "source_kind": params["source_kind"], "sales_end": params["sales_end"],
            "analysis_mode": params["analysis_mode"], "platform_type": params["platform_type"],
            "activity_start": params["activity_start"], "activity_end": params["activity_end"],
            "activity_factor": params["activity_factor"], "quantity_filter": "all", "limit": CHUNK_SIZE, "offset": 0}
        if params["exclude_operating_order_id"] is not None:
            chunk_payload["exclude_operating_order_id"] = params["exclude_operating_order_id"]
        trusted_request = SimpleNamespace(user=actor, data=chunk_payload, _trusted_replenishment_chunk_ids=ids)
        from apps.supply_chain.replenishment import ReplenishmentReferences
        response = ReplenishmentReferences().post(trusted_request)
        lines = response.data.get("data", {}).get("lines", [])
        if response.status_code >= 400 or len(lines) != len(ids):
            raise ValidationError("商品授权或有效状态变化，请重新生成全量清单。")
        creates = []
        counts = {"positive": 0, "zero": 0, "unknown": 0, "awaiting_procurement": 0, "arrival_gap": 0}
        for line in lines:
            qty = line.get("suggested_quantity")
            bucket = "unknown" if qty is None else ("positive" if int(qty) > 0 else "zero")
            counts[bucket] += 1
            if Decimal(str(line.get("submitted_demand") or "0")) > 0:
                counts["awaiting_procurement"] += 1
            if line.get("risk_level") == "arrival_gap":
                counts["arrival_gap"] += 1
            creates.append(ReplenishmentCalculationRow(job=job, sku_id=int(line["sku_id"]),
                sku_code=str(line.get("sku_code") or "")[:160], legacy_sku_code=str(line.get("legacy_sku_code") or "")[:160],
                product_name=str(line.get("product_name") or "")[:240], suggested_quantity=qty,
                risk_level=str(line.get("risk_level") or "")[:32],
                has_submitted_demand=Decimal(str(line.get("submitted_demand") or "0")) > 0,
                # Internal view calls bypass response rendering; evidence may contain
                # datetime/date/Decimal values that JSONField cannot encode itself.
                payload=json.loads(json.dumps(line, cls=DjangoJSONEncoder))))
        with transaction.atomic():
            _restore_actor(job)
            if (_scope_signature(actor) != job.permission_signature or
                    not ReplenishmentStrategy.objects.filter(pk=job.strategy_id, tenant_id=job.tenant_id,
                        version=job.strategy_version, active=True).exists() or job.business_date != business_date()):
                raise PermissionDenied("授权、策略或业务日期已变化。")
            _active_job(job, token)
            current = ReplenishmentCalculationJob.objects.select_for_update().get(pk=job.pk)
            if current.lease_token != token or current.next_offset != offset or current.status != "running":
                return
            ReplenishmentCalculationRow.objects.bulk_create(creates, batch_size=CHUNK_SIZE)
            next_offset = offset + len(ids)
            aggregate = {k: int(current.counts.get(k, 0)) + counts[k] for k in counts}
            updates = {"processed": next_offset, "next_offset": next_offset, "counts": aggregate,
                "lease_token": None, "lease_expires_at": None, "updated_at": timezone.now()}
            if next_offset >= current.total:
                updates.update(status="completed", expires_at=timezone.now() + JOB_TTL)
            ReplenishmentCalculationJob.objects.filter(pk=current.pk, lease_token=token).update(**updates)
            if next_offset < current.total:
                transaction.on_commit(lambda: _dispatch_followup(current.pk))
    except Exception as exc:
        message = "全量补货计算未完成，请重新生成或缩小范围。"
        if isinstance(exc, PermissionDenied): message = "数据权限已变化，请重新生成清单。"
        elif isinstance(exc, ValidationError): message = "策略、授权或业务数据已变化，请重新生成清单。"
        ReplenishmentCalculationJob.objects.filter(pk=job.pk, status="running", lease_token=token).update(
            status="failed", error=message, lease_token=None, lease_expires_at=None)


def purge_replenishment_jobs():
    now = timezone.now()
    expired = ReplenishmentCalculationJob.objects.filter(
        Q(status="completed", expires_at__lte=now) |
        Q(status__in=["queued", "running"], hard_deadline__lte=now) |
        Q(status__in=["cancelled", "failed", "expired"])
    ).exclude(status__in=["queued", "running"], lease_expires_at__gt=now)
    row_ids = list(ReplenishmentCalculationRow.objects.filter(job__in=expired).values_list("pk", flat=True)[:2000])
    if row_ids: ReplenishmentCalculationRow.objects.filter(pk__in=row_ids).delete()
    empty_ids = list(expired.annotate(row_count=models.Count("rows")).filter(row_count=0).values_list("pk", flat=True)[:20])
    if empty_ids: ReplenishmentCalculationJob.objects.filter(pk__in=empty_ids).delete()


def recover_replenishment_jobs():
    """Re-enqueue at most 20 jobs whose dispatch or worker lease appears lost."""
    now = timezone.now()
    candidates = ReplenishmentCalculationJob.objects.filter(hard_deadline__gt=now, updated_at__lte=now - timedelta(seconds=60)).filter(
        Q(status="queued") | Q(status="running") & (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
    ).order_by("created_at").values_list("pk", flat=True)[:20]
    recovered = 0
    for job_id in candidates:
        with transaction.atomic():
            job = ReplenishmentCalculationJob.objects.select_for_update().filter(pk=job_id).first()
            if not job or job.hard_deadline <= now or job.updated_at > now - timedelta(seconds=60):
                continue
            if not (job.status == "queued" or (job.status == "running" and
                    (job.lease_expires_at is None or job.lease_expires_at <= now))):
                continue
            ReplenishmentCalculationJob.objects.filter(pk=job.pk).update(updated_at=now)
            transaction.on_commit(lambda current_id=job.pk: _dispatch_followup(current_id))
            recovered += 1
    return recovered


def _dispatch_followup(job_id):
    try:
        _enqueue(job_id)
    except Exception:
        ReplenishmentCalculationJob.objects.filter(pk=job_id, status="running", lease_token__isnull=True).update(
            status="failed", error="补货计算队列暂不可用，请重新生成。")
