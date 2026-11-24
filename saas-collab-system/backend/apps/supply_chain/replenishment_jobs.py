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
from .snapshot_payload import pack_payload
from apps.supply_chain.views import ReadAPI
from apps.masterdata.models import CountrySiteMaster

CHUNK_SIZE = 20
MAX_CANDIDATES = 100_000
JOB_TTL = timedelta(minutes=15)
DAILY_JOB_TTL = timedelta(days=7)
JOB_DEADLINE = timedelta(hours=2)
LEASE_DURATION = timedelta(minutes=3)
SCOPE_CODES = (SC_VIEW, SC_MANAGE, operating_domain.VIEW, operating_domain.MANAGE,
               country_decisions.INVENTORY, country_decisions.SALES, SUMMARY_PERMISSION)
RESOURCE_CODES = {country_decisions.INVENTORY: "commerce.inventory",
                  country_decisions.SALES: "sales_management.sales",
                  SUMMARY_PERMISSION: "sales_management.supply_summary"}


def _scope_signature(actor, *, business_day=None):
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
        "membership": getattr(actor, "_active_membership_id", None), "business_date": business_day or business_date(),
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
    meta = ReplenishmentCalculationJob.objects.filter(pk=job_id).values_list("config", flat=True).first() or {}
    options = {}
    if meta.get("daily"):
        from .replenishment_schedule import DAILY_QUEUE, daily_task_budget, night_deadline
        now = timezone.now()
        budget = daily_task_budget(now)
        if budget < 15:
            return
        options = {"queue": DAILY_QUEUE, "soft_time_limit": max(10, budget - 30), "time_limit": budget, "countdown": 2,
                   "expires": night_deadline(now)}
    current_app.send_task("apps.supply_chain.tasks.run_replenishment_calculation", args=[str(job_id)], retry=False, **options)


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
        product_type="standard").exclude(inventory_type="virtual").order_by("sku_code", "pk")
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
    if values["analysis_mode"] == "platform":
        config["calculation_algorithm"] = "platform-own-sales-v1"
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
                    "awaiting_procurement": 0, "arrival_gap": 0, "observed": 0},
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
        if job.config.get("daily"):
            from .daily_replenishment import daily_job_for_actor
            return daily_job_for_actor(request.user, job.pk)
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


def _legacy_replenishment_reference(line):
    """Persist the legacy trial result with the same inputs as the daily row."""
    from decimal import Decimal, InvalidOperation

    def number(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = Decimal(str(value))
            return parsed if parsed.is_finite() else None
        except (InvalidOperation, ValueError):
            return None

    evidence = (line.get("formula_evidence") or {}).get("sales") or {}
    observed = (line.get("recognized_reference") or {}).get("observed_sales_windows") or {}
    windows = {str(item["days"]): item for item in line.get("sales_windows", ()) if item.get("days")}
    units, partial = [], False
    for days in ("7", "15", "30"):
        window = windows.get(days, {})
        value = number((evidence.get(days) or {}).get("units"))
        if value is None:
            value = number(window.get("units"))
        if value is None:
            seen = number(observed.get(days))
            if seen is None:
                seen = number(window.get("recognized_units"))
            if seen is not None and seen > 0:
                value, partial = seen, True
        units.append(value)
    daily = None if None in units else sum(
        amount / days * Decimal(weight)
        for amount, days, weight in zip(units, (7, 15, 30), ("0.5", "0.3", "0.2"))
    )
    stock = number(line.get("available_stock"))
    if stock is None:
        stock = number((line.get("recognized_reference") or {}).get("observed_available_stock"))
        if stock is None:
            known = []
            for warehouse in line.get("warehouses", ()):
                amount = number(warehouse.get("available_qty"))
                if amount is None:
                    amount = number(warehouse.get("last_synced_qty"))
                if amount is not None:
                    known.append(amount)
            stock = sum(known) if known else None
        partial |= stock is not None
    pipeline = line.get("pipeline") or {}
    transit = number(pipeline.get("transporting")) if pipeline.get("authorized") else None
    production = number(pipeline.get("production_unshipped")) if pipeline.get("authorized") else None
    quantity = None if None in (daily, stock, transit, production) else 90 * daily - stock - transit - production
    return {"daily": float(daily) if daily is not None else None,
            "quantity": float(quantity) if quantity is not None else None, "partial": partial}


class ReplenishmentJobRows(ReplenishmentJobDetail):
    default_quantity_filter = "positive"

    def row_queryset(self, request, job):
        return ReplenishmentCalculationRow.objects.filter(job=job)

    def result_identity(self, job):
        return {}

    @staticmethod
    def suggestion_queryset(qs):
        from django.db.models import Case, DecimalField, F, Value, When
        from django.db.models.fields.json import KeyTextTransform
        from django.db.models.functions import Cast, Ceil, Coalesce, Greatest, NullIf

        field = DecimalField(max_digits=30, decimal_places=8)

        def number(path):
            return Cast(NullIf(KeyTextTransform.from_lookup('payload__' + path), Value('null')), field)

        reference = 'recognized_reference__'
        ambiguous = Q()
        for issue in ('dispatch_allocation_overallocated', 'shipment_receipt_overallocated',
                      'wms_allocation_requires_review', 'wms_receipt_overlap_unresolved'):
            ambiguous |= Q(payload__pipeline__issues__icontains=issue)
        incoming = Case(When(Q(payload__pipeline__authorized=True) & ~ambiguous,
                             then=Coalesce(number('pipeline__effective_incoming'), Value(0), output_field=field) + Coalesce(number('pipeline__unknown_eta'), Value(0), output_field=field)),
                        default=Value(0), output_field=field)
        zero = Value(0, output_field=field)
        legacy = Greatest(zero, Ceil(number(reference + 'target_stock_reference')
            - number(reference + 'observed_available_stock') - incoming
            - Coalesce(number('submitted_demand'), zero) - Coalesce(number('draft_reserved_demand'), zero)))
        observed = Case(When(payload__recognized_reference__has_observed_basis=True,
            then=Case(When(payload__recognized_reference__confirmed_deductions__isnull=False,
                           then=number(reference + 'quantity_reference')),
                      default=legacy, output_field=field)), output_field=field)
        return qs.annotate(display_suggestion=Coalesce(Cast(F('suggested_quantity'), field), observed))

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
        quantity_filter = request.query_params.get("quantity_filter", self.default_quantity_filter)
        if quantity_filter not in {"positive", "all", "zero", "unknown", "observed", "with_data", "action", "purchase", "expedite", "no_sales", "sufficient", "inactive"}:
            raise ValidationError({"quantity_filter": "筛选值无效。"})
        qs = self.suggestion_queryset(self.row_queryset(request, job))
        from django.db.models import Count
        display_counts = {}
        if not (request.query_params.get('group_by') == 'sku' and request.query_params.get('spu_id')):
            display_counts = qs.aggregate(suggested=Count('pk', filter=Q(display_suggestion__gt=0)),
                                          pending=Count('pk', filter=Q(display_suggestion__isnull=True)),
                                          purchase=Count('pk', filter=Q(payload__business_decision__category='purchase')),
                                          expedite=Count('pk', filter=Q(payload__business_decision__requires_expedite=True)),
                                          no_sales=Count('pk', filter=Q(payload__business_decision__category='no_sales')),
                                          sufficient=Count('pk', filter=Q(payload__business_decision__category='sufficient')))
        if quantity_filter in {'action', 'purchase', 'expedite', 'no_sales', 'sufficient', 'inactive'}:
            categories_filter = ['purchase', 'expedite'] if quantity_filter == 'action' else [quantity_filter]
            selected = Q(payload__business_decision__category__in=categories_filter)
            if quantity_filter == 'expedite':
                selected = Q(payload__business_decision__requires_expedite=True)
            legacy = Q(payload__business_decision__isnull=True)
            if 'purchase' in categories_filter:
                selected |= legacy & Q(display_suggestion__gt=0)
            if 'expedite' in categories_filter:
                selected |= legacy & Q(risk_level='arrival_gap')
            qs = qs.filter(selected)
        elif quantity_filter == "positive": qs = qs.filter(suggested_quantity__gt=0)
        elif quantity_filter == "zero": qs = qs.filter(suggested_quantity=0)
        elif quantity_filter == "unknown": qs = qs.filter(suggested_quantity__isnull=True)
        elif quantity_filter == "observed":
            qs = qs.filter(Q(suggested_quantity__gt=0) | Q(payload__recognized_reference__has_observed_basis=True))
        elif quantity_filter == "with_data":
            from django.db.models import DecimalField, Value
            from django.db.models.fields.json import KeyTextTransform
            from django.db.models.functions import Cast, NullIf
            def numeric(path):
                return Cast(NullIf(KeyTextTransform.from_lookup("payload__" + path), Value("null")),
                            DecimalField(max_digits=24, decimal_places=4))
            qs = qs.alias(
                known_stock=numeric("available_stock"),
                observed_stock=numeric("recognized_reference__observed_available_stock"),
                sales_7=numeric("formula_evidence__sales__7__units"),
                sales_15=numeric("formula_evidence__sales__15__units"),
                sales_30=numeric("formula_evidence__sales__30__units"),
                observed_sales=numeric("recognized_reference__observed_sales_windows__30"),
                pending_purchase=numeric("pipeline__production_unshipped"),
                incoming=numeric("pipeline__effective_incoming"),
                demand=numeric("submitted_demand"),
            ).filter(
                Q(known_stock__isnull=False) | Q(observed_stock__isnull=False) |
                Q(sales_7__isnull=False) | Q(sales_15__isnull=False) | Q(sales_30__isnull=False) |
                Q(observed_sales__gt=0) | Q(pending_purchase__gt=0) | Q(incoming__gt=0) |
                Q(demand__gt=0) | Q(suggested_quantity__isnull=False)
            )
        risk = request.query_params.get("risk_filter", "").strip()
        if risk and risk not in {"awaiting_procurement", "arrival_gap", "data_check", "new_or_zero_sales",
                "out_of_stock", "replenish", "normal", "manual_review"}:
            raise ValidationError({"risk_filter": "风险筛选值无效。"})
        if risk == "awaiting_procurement": qs = qs.filter(has_submitted_demand=True)
        elif risk: qs = qs.filter(risk_level=risk)
        term = request.query_params.get("search", "").strip()
        from apps.products.models import ProductCategory, ProductSKU
        from django.db.models import DecimalField, F, OuterRef, Subquery
        from django.db.models.fields.json import KeyTextTransform
        from django.db.models.functions import Cast, NullIf
        from django.db.models import Value

        categories = list(ProductCategory.objects.filter(tenant_id=job.tenant_id)
                          .values('id', 'parent_id', 'name'))
        products = ProductSKU.objects.filter(tenant_id=job.tenant_id)
        if term:
            qs = qs.filter(Q(sku_code__icontains=term) | Q(legacy_sku_code__icontains=term) |
                Q(product_name__icontains=term) | Q(sku_id__in=products.filter(
                    Q(spu__spu_code__icontains=term) | Q(spu__legacy_spu_code__icontains=term) |
                    Q(spu__product_name__icontains=term)).values('pk')))
        selected = request.query_params.get('category_ids', '')
        if selected:
            try:
                ids = {int(value) for value in selected.split(',')}
            except ValueError:
                raise ValidationError({'category_ids': '品类参数无效。'})
            if not ids <= {category['id'] for category in categories}:
                raise ValidationError({'category_ids': '品类参数无效。'})
            for _ in range(2):
                ids.update([category['id'] for category in categories if category['parent_id'] in ids])
            qs = qs.filter(sku_id__in=products.filter(spu__category_node_id__in=ids).values('pk'))
        abc_grade = request.query_params.get("abc_grade", "").strip()
        if abc_grade:
            if abc_grade not in {"A", "B", "C", "new", "no_sales", "unavailable"}:
                raise ValidationError({"abc_grade": "ABC 等级无效。"})
            from apps.sales_management.abc_access import filter_skus
            abc_products = filter_skus(request.user, job.country, products, abc_grade)
            qs = qs.filter(sku_id__in=abc_products.values("pk"))
        group_by = request.query_params.get('group_by', '').strip()
        if group_by not in {'', 'spu', 'sku'}:
            raise ValidationError({'group_by': '分组参数无效。'})
        if group_by in {'spu', 'sku'}:
            from django.db.models import Count, Sum, DecimalField, Value
            from django.db.models.functions import Coalesce
            if group_by == 'sku' and request.query_params.get('spu_id'):
                try:
                    spu_id = int(request.query_params['spu_id'])
                except (TypeError, ValueError):
                    raise ValidationError({'spu_id': 'SPU参数无效。'})
                spu = products.filter(spu_id=spu_id).values_list('spu_id', flat=True).first()
                if spu is None:
                    raise ValidationError({'spu_id': 'SPU参数无效。'})
                qs = qs.filter(sku_id__in=products.filter(spu_id=spu_id).values('pk'))
                count = qs.count()
                page = list(qs.order_by('sku_id')[offset:offset + limit])
                codes = {sku_id: (spu_code, legacy, name, image, status) for sku_id, spu_code, legacy, name, image, status in products.filter(
                    pk__in=[row.sku_id for row in page]).values_list('pk', 'spu__spu_code', 'spu__legacy_spu_code', 'spu__product_name', 'image_url', 'spu__sales_status')}
                from .replenishment import restore_snapshot_suggestion
                rows = []
                for row in page:
                    values = codes.get(row.sku_id, ('', '', '', '', ''))
                    image_url = f'/api/internal/supply-chain/v2/options/skus/{row.sku_id}/image/' if values[3] and values[4] == 'on_sale' else ''
                    rows.append(dict(restore_snapshot_suggestion(row.payload), sku_id=row.sku_id, spu_id=spu_id,
                        spu_code=values[0], legacy_spu_code=values[1], spu_name=values[2],
                        image_preview_url=image_url,
                        legacy_reference=row.payload.get('legacy_reference') or _legacy_replenishment_reference(row.payload)))
                from apps.sales_management.abc_access import decorate_rows
                abc_meta = decorate_rows(request.user, job.country, rows)
                return Response({'data': {'abc_meta': abc_meta, 'status': job.status, 'rows': rows, 'count': count,
                    'total': job.total, 'processed': job.processed, 'counts': {**job.counts, **display_counts},
                    'limit': limit, 'offset': offset, 'has_more': offset + len(rows) < count,
                    'quantity_filter': quantity_filter, 'group_by': 'sku', 'spu_id': spu_id,
                    'categories': categories, **self.result_identity(job)}})
            if group_by == 'spu':
                from apps.products.models import ProductSPU
                from django.db.models import Case, When, IntegerField, Min
                import hashlib
                sort = request.query_params.get('sort', 'urgency')
                direction = request.query_params.get('direction', 'asc')
                allowed = {'urgency', 'spu_code', 'legacy_spu_code', 'spu_name', 'sku_count',
                           'sales_7', 'sales_15', 'sales_30', 'available_stock', 'production_unshipped',
                           'incoming_quantity', 'suggested_quantity'}
                if sort not in allowed or direction not in {'asc', 'desc'}:
                    raise ValidationError({'sort': '排序参数无效。'})
                from django.db.models.expressions import RawSQL
                sku_table = ProductSKU._meta.db_table
                spu_table = ProductSPU._meta.db_table
                row_table = ReplenishmentCalculationRow._meta.db_table
                def grouped_rows(query):
                    return query.extra(tables=[sku_table, spu_table], where=[
                        f'{row_table}.sku_id = {sku_table}.id',
                        f'{sku_table}.spu_id = {spu_table}.id',
                        f'{sku_table}.tenant_id = %s', f'{spu_table}.tenant_id = %s'],
                        params=[job.tenant_id, job.tenant_id]).annotate(
                            report_spu_id=RawSQL(f'{sku_table}.spu_id', []))
                matched = grouped_rows(qs)
                matched_ids = products.filter(pk__in=qs.order_by().values('sku_id')).order_by().values('spu_id').distinct()
                full = grouped_rows(self.suggestion_queryset(self.row_queryset(request, job))).filter(
                    sku_id__in=products.filter(spu_id__in=Subquery(matched_ids)).values('pk'))
                field = DecimalField(max_digits=30, decimal_places=8)
                def numeric(path):
                    # JSON object keys '7'/'15'/'30' are not array indexes.
                    from django.db import connection
                    from django.db.models import TextField
                    if any(part.isdigit() for part in path.split('__')) and connection.vendor in {'mysql', 'sqlite'}:
                        quoted_path = '$.' + '.'.join(json.dumps(part) for part in path.split('__'))
                        payload_column = connection.ops.quote_name(row_table) + '.payload'
                        function = 'JSON_UNQUOTE(JSON_EXTRACT(' if connection.vendor == 'mysql' else 'JSON_EXTRACT('
                        suffix = ', %s))' if connection.vendor == 'mysql' else ', %s)'
                        raw = RawSQL(function + payload_column + suffix, [quoted_path], output_field=TextField())
                    else:
                        raw = KeyTextTransform.from_lookup('payload__' + path)
                    return Cast(NullIf(raw, Value('null')), field)
                def known(*paths):
                    return Coalesce(*[numeric(path) for path in paths], output_field=field)
                stock = known('available_stock', 'recognized_reference__observed_available_stock')
                incoming = known('business_decision__incoming_quantity', 'pipeline__effective_incoming')
                metrics = full.order_by().values('report_spu_id').annotate(
                    sku_count=Count('pk'), suggested_quantity=Sum('display_suggestion'),
                    available_stock=Sum(stock),
                    sales_7=Sum(known('formula_evidence__sales__7__units', 'recognized_reference__observed_sales_windows__7')),
                    sales_15=Sum(known('formula_evidence__sales__15__units', 'recognized_reference__observed_sales_windows__15')),
                    sales_30=Sum(known('formula_evidence__sales__30__units', 'recognized_reference__observed_sales_windows__30')),
                    production_unshipped=Sum(numeric('pipeline__production_unshipped')),
                    incoming_quantity=Sum(incoming),
                    purchase_count=Count('pk', filter=Q(payload__business_decision__category='purchase')),
                    expedite_count=Count('pk', filter=Q(payload__business_decision__requires_expedite=True)),
                    urgency=Min(Case(When(payload__business_decision__requires_expedite=True, then=Value(0)),
                        When(payload__business_decision__category='purchase', then=Value(1)),
                        default=Value(2), output_field=IntegerField())))
                if sort in {'spu_code', 'legacy_spu_code', 'spu_name'}:
                    column = 'product_name' if sort == 'spu_name' else sort
                    metrics = metrics.annotate(group_sort=Min(RawSQL(f'{spu_table}.{column}', [])))
                    sort = 'group_sort'
                count = metrics.count()
                ordering = F(sort).asc(nulls_last=True) if direction == 'asc' else F(sort).desc(nulls_last=True)
                page_groups = list(metrics.order_by(ordering, 'report_spu_id')[offset:offset + limit])
                page_ids = [item['report_spu_id'] for item in page_groups]
                spus = {item['id']: item for item in ProductSPU.objects.filter(
                    tenant_id=job.tenant_id, pk__in=page_ids).values('id', 'spu_code', 'legacy_spu_code', 'product_name')}
                matches = {item['report_spu_id']: item['matched_sku_count'] for item in matched.filter(
                    sku_id__in=products.filter(spu_id__in=page_ids).values('pk')).order_by().values('report_spu_id').annotate(matched_sku_count=Count('pk'))}
                representatives = {}
                # Stable pseudo-random representative among authorized on-sale snapshot SKUs.
                images = products.filter(spu_id__in=page_ids, is_active=True, spu__sales_status='on_sale',
                    pk__in=self.row_queryset(request, job).values('sku_id')).exclude(image_url__isnull=True).exclude(image_url='')
                for sku_id, sid in images.values_list('pk', 'spu_id').iterator(chunk_size=200):
                    score = hashlib.sha256(f'{job.pk}:{sku_id}'.encode()).hexdigest()
                    if sid not in representatives or score < representatives[sid][0]:
                        representatives[sid] = (score, sku_id)
                rows = []
                for metric in page_groups:
                    sid = metric.pop('report_spu_id'); spu = spus.get(sid, {})
                    rep = representatives.get(sid, (None, None))[1]
                    rows.append({**metric, 'spu_id': sid, 'spu_code': spu.get('spu_code', ''),
                        'legacy_spu_code': spu.get('legacy_spu_code', ''), 'spu_name': spu.get('product_name', ''),
                        'matched_sku_count': matches.get(sid, 0), 'image_sku_id': rep,
                        'image_preview_url': f'/api/internal/supply-chain/v2/options/skus/{rep}/image/' if rep else ''})
                from apps.sales_management.abc_access import decorate_rows
                abc_meta = decorate_rows(request.user, job.country, rows)
                return Response({'data': {'abc_meta': abc_meta, 'status': job.status, 'rows': rows, 'count': count, 'total': job.total,
                    'processed': job.processed, 'counts': {**job.counts, **display_counts}, 'limit': limit,
                    'offset': offset, 'has_more': offset + len(rows) < count, 'quantity_filter': quantity_filter,
                    'group_by': 'spu', 'categories': categories, **self.result_identity(job)}})
        sort = request.query_params.get('sort', 'sku_code')
        direction = request.query_params.get('direction', 'asc')
        numeric_paths = {
            'sales_7': 'formula_evidence__sales__7__units',
            'sales_15': 'formula_evidence__sales__15__units',
            'sales_30': 'formula_evidence__sales__30__units',
            'available_stock': 'available_stock',
            'production_unshipped': 'pipeline__production_unshipped',
            'valid_incoming': 'valid_incoming',
            'submitted_demand': 'submitted_demand',
            'legacy_daily_sales': 'legacy_reference__daily',
            'legacy_purchase_quantity': 'legacy_reference__quantity',
        }
        if direction not in {'asc', 'desc'} or sort not in {
            'sku_code', 'legacy_sku_code', 'spu_code', 'legacy_spu_code', 'product_name', 'suggested_quantity', 'urgency', *numeric_paths,
        }:
            raise ValidationError({'sort': '排序参数无效。'})
        if sort == 'urgency':
            from django.db.models import Case, IntegerField, When
            qs = qs.annotate(urgency=Case(
                When(payload__business_decision__requires_expedite=True, then=Value(0)),
                When(payload__business_decision__category='purchase', then=Value(1)),
                default=Value(2), output_field=IntegerField()))
        if sort == 'suggested_quantity':
            sort = 'display_suggestion'
        if sort in {'spu_code', 'legacy_spu_code'}:
            qs = qs.annotate(report_sort=Subquery(products.filter(pk=OuterRef('sku_id')).values('spu__' + sort)[:1]))
            sort = 'report_sort'
        elif sort in numeric_paths:
            raw = KeyTextTransform.from_lookup('payload__' + numeric_paths[sort])
            qs = qs.annotate(report_sort=Cast(NullIf(raw, Value('null')), DecimalField(max_digits=24, decimal_places=4)))
            sort = 'report_sort'
        count = qs.count()
        ordering = F(sort).asc(nulls_last=True) if direction == 'asc' else F(sort).desc(nulls_last=True)
        page = list(qs.order_by(ordering, 'sku_id')[offset:offset + limit])
        codes = {sku_id: (spu, legacy) for sku_id, spu, legacy in products.filter(
            pk__in=[row.sku_id for row in page]).values_list('pk', 'spu__spu_code', 'spu__legacy_spu_code')}
        from .replenishment import restore_snapshot_suggestion
        rows = [dict(restore_snapshot_suggestion(row.payload), spu_code=codes.get(row.sku_id, ('', ''))[0],
                     legacy_spu_code=codes.get(row.sku_id, ('', ''))[1],
                     legacy_reference=row.payload.get("legacy_reference") or _legacy_replenishment_reference(row.payload)) for row in page]
        from apps.sales_management.abc_access import decorate_rows
        abc_meta = decorate_rows(request.user, job.country, rows)
        return Response({"data": {"abc_meta": abc_meta, "status": job.status, "rows": rows, "count": count,
            "total": job.total, "processed": job.processed, "counts": {**job.counts, **display_counts},
            "limit": limit, "offset": offset, "has_more": offset + len(rows) < count,
            "quantity_filter": quantity_filter, "categories": categories, **self.result_identity(job)}})



def _daily_calculation(job):
    meta = job.config.get("daily")
    return isinstance(meta, dict) and bool(meta.get("key")) and meta.get("day") == job.business_date.isoformat()


def _valid_calculation_day(job):
    delta = (business_date() - job.business_date).days
    return delta == 0 or (_daily_calculation(job) and delta == 1)


def _active_job(job, token):
    job.refresh_from_db()
    if (job.status != "running" or job.lease_token != token or job.hard_deadline <= timezone.now() or
        not _valid_calculation_day(job)):
        raise RuntimeError("补货计算任务已取消、过期或失去处理租约。")


def run_replenishment_calculation(job_id):
    now = timezone.now(); token = uuid.uuid4()
    meta = ReplenishmentCalculationJob.objects.filter(pk=job_id).values_list("config", flat=True).first() or {}
    lease_duration = LEASE_DURATION
    if meta.get("daily"):
        from .replenishment_schedule import in_night_window, DAILY_LEASE_SECONDS
        if not in_night_window(now):
            return
        lease_duration = timedelta(seconds=DAILY_LEASE_SECONDS)
    claimed = ReplenishmentCalculationJob.objects.filter(pk=job_id, status__in=["queued", "running"],
        hard_deadline__gt=now).filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)).update(
            status="running", lease_token=token, lease_expires_at=now + lease_duration, updated_at=now)
    if not claimed:
        return
    job = ReplenishmentCalculationJob.objects.select_related("requested_by", "country", "strategy", "tenant").get(pk=job_id)
    try:
        actor = _restore_actor(job)
        if _scope_signature(actor, business_day=job.business_date if _daily_calculation(job) else None) != job.permission_signature:
            raise PermissionDenied("授权范围已变化。")
        if not ReplenishmentStrategy.objects.filter(pk=job.strategy_id, tenant_id=job.tenant_id,
                version=job.strategy_version, active=True).exists():
            raise ValidationError("补货策略已变化或停用。")
        if not _valid_calculation_day(job):
            raise ValidationError("业务日期已变化。")
        offset = job.next_offset
        from .replenishment_schedule import DAILY_CHUNK_SIZE
        batch_size = DAILY_CHUNK_SIZE if _daily_calculation(job) else CHUNK_SIZE
        ids = job.candidate_ids[offset:offset + batch_size]
        if not ids:
            with transaction.atomic():
                _active_job(job, token)
                ReplenishmentCalculationJob.objects.filter(pk=job.pk, lease_token=token).update(
                    status="completed", expires_at=timezone.now() + (DAILY_JOB_TTL if job.config.get("daily") else JOB_TTL), lease_token=None,
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
        trusted_request = SimpleNamespace(user=actor, data=chunk_payload, _trusted_replenishment_chunk_ids=ids,
            _trusted_replenishment_batch_size=batch_size,
            _trusted_replenishment_business_day=job.business_date if _daily_calculation(job) else None)
        from apps.supply_chain.replenishment import ReplenishmentReferences
        response = ReplenishmentReferences().post(trusted_request)
        lines = response.data.get("data", {}).get("lines", [])
        if response.status_code >= 400 or len(lines) != len(ids):
            raise ValidationError("商品授权或有效状态变化，请重新生成全量清单。")
        creates = []
        counts = {"positive": 0, "zero": 0, "unknown": 0, "awaiting_procurement": 0, "arrival_gap": 0, "observed": 0}
        for line in lines:
            qty = line.get("suggested_quantity")
            bucket = "unknown" if qty is None else ("positive" if int(qty) > 0 else "zero")
            counts[bucket] += 1
            if bucket == "positive" or (line.get("recognized_reference") or {}).get("has_observed_basis"):
                counts["observed"] += 1
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
                payload=pack_payload(json.loads(json.dumps(line, cls=DjangoJSONEncoder)))))
        with transaction.atomic():
            _restore_actor(job)
            if (_scope_signature(actor, business_day=job.business_date if _daily_calculation(job) else None) != job.permission_signature or
                    not ReplenishmentStrategy.objects.filter(pk=job.strategy_id, tenant_id=job.tenant_id,
                        version=job.strategy_version, active=True).exists() or not _valid_calculation_day(job)):
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
                updates.update(status="completed", expires_at=timezone.now() + (DAILY_JOB_TTL if current.config.get("daily") else JOB_TTL))
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
    ).filter(~Q(config__has_key="daily") | Q(expires_at__lte=now)).exclude(status__in=["queued", "running"], lease_expires_at__gt=now)
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
