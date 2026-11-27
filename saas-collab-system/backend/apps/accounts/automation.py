"""Read-only automation catalogue. Runtime observations are separately collected."""
import json
from datetime import timedelta
from uuid import UUID
from pathlib import Path
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.views import APIView
from apps.common.responses import success_response
from apps.permissions.api_permissions import InternalSuperuserPermission
from apps.integrations.models import SyncJob, SyncRun
from django.apps import apps

if apps.is_installed("apps.flash_sales"):
    from apps.flash_sales.models import Plan, Batch
else:
    Plan = Batch = None

BEAT_NAMES = {
    "dispatch-finance-summary-calculations": "财务汇总计算",
    "dispatch-order-aftersales-sync": "订单售后同步",
    "purge-expired-report-analysis": "过期报表分析清理",
    "dispatch-supply-notifications": "供应商群通知派发",
    "dispatch-feishu-deliveries": "飞书消息投递",
    "activate-due-config-versions": "到期配置版本启用",
    "dispatch-daily-affiliate-order-attribution-refreshes": "联盟订单归因刷新",
    "refresh-due-integration-credentials": "集成凭据刷新",
    "refresh-country-cny-exchange-rates": "人民币汇率刷新",
    "mark-overdue-sample-fulfillments": "逾期样品履约检查",
    "nightly-sample-video-completion": "样品视频完成检查",
    "dispatch-due-readonly-sync-jobs": "到期同步任务派发",
    "dispatch-stale-governance-evaluations": "滞留治理评估派发",
    "reconcile-stale-governance-evaluations": "滞留治理评估核对",
    "dispatch-stale-pilot-executions": "滞留试运行派发",
    "build-inventory-decision-views": "库存决策视图构建",
    "refresh-inventory-decisions": "库存决策刷新",
    "dispatch-order-warehouse-lookups": "仓库订单查询派发",
    "dispatch-sync-task-shopee-flash-plans": "闪购计划派发",
    "dispatch-shopee-flash-sales": "闪购执行派发",
}
EXTERNAL = {
    "replenishment": ("补货建议", "systemd"),
    "abc": ("商品 ABC", "cron"),
    "inventory_warnings": ("库存预警", "cron"),
    "first_sale": ("首次销售日期维护", "cron"),
    "backup": ("备份维护", "systemd"),
    "paired_backup": ("配对备份", "systemd"),
    "board": ("大屏时段控制", "systemd"),
    "inbound_feishu": ("入库飞书通知", "systemd"),
    "video_cutoff": ("视频夜间截止", "systemd"),
}

def validate_observations(data):
    if not isinstance(data, dict) or set(data) != {"tasks"}:
        raise ValueError("Invalid root")
    rows = data["tasks"]
    allowed_ids = set(EXTERNAL) | {"beat:" + key for key in set(settings.CELERY_BEAT_SCHEDULE) | set(BEAT_NAMES)}
    if not isinstance(rows, list) or len(rows) > len(allowed_ids):
        raise ValueError("Invalid tasks")
    found = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"id", "observed_at", "enabled", "state", "schedule", "next_run_at", "last_result", "runs"}:
            raise ValueError("Invalid fields")
        key = row["id"]
        if key not in allowed_ids or key in found or (row["enabled"] is not None and type(row["enabled"]) is not bool):
            raise ValueError("Invalid identity")
        if row["state"] not in {"idle", "running", "failed", "paused", "unknown"}:
            raise ValueError("Invalid state")
        runs = row.get("runs", [])
        if not isinstance(runs, list) or len(runs) > 100:
            raise ValueError("Invalid runs")
        stamps = [row["observed_at"], row.get("next_run_at")]
        for run in runs:
            if not isinstance(run, dict) or set(run) - {"id", "status", "started_at", "finished_at", "result", "tenant_id"} or not {"id", "status", "started_at", "finished_at", "result"}.issubset(run):
                raise ValueError("Invalid run fields")
            if "tenant_id" in run and (type(run["tenant_id"]) is not int or run["tenant_id"] < 1):
                raise ValueError("Invalid tenant")
            if not isinstance(run["id"], str) or len(run["id"]) > 100:
                raise ValueError("Invalid run id")
            if run["status"] not in {"success", "failed", "running", "queued", "skipped", "partial", "unknown"}:
                raise ValueError("Invalid run status")
            if not isinstance(run["result"], str) or len(run["result"]) > 200:
                raise ValueError("Invalid result")
            stamps.extend([run["started_at"], run["finished_at"]])
        for field in ("schedule", "last_result"):
            if row.get(field) is not None and (not isinstance(row[field], str) or len(row[field]) > 200):
                raise ValueError("Invalid text")
        for value in stamps:
            if value is not None:
                stamp = parse_datetime(value)
                if not stamp or timezone.is_naive(stamp):
                    raise ValueError("Invalid timestamp")
        if parse_datetime(row["observed_at"]) > timezone.now() + timedelta(minutes=1):
            raise ValueError("Future timestamp")
        found[key] = row
    return found


def observations():
    path = getattr(settings, "AUTOMATION_OBSERVATIONS_FILE", "")
    if not path:
        return {}
    try:
        if Path(path).stat().st_size > 131072:
            return {}
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return validate_observations(data)
    except (OSError, ValueError, KeyError, TypeError):
        return {}

def safe_sync_schedule(scope, schedule_type):
    scope = scope if isinstance(scope, dict) else {}
    schedule = scope.get("schedule")
    schedule = schedule if isinstance(schedule, dict) else {}
    allowed = {"type", "timezone", "interval_minutes", "local_time", "time", "hour", "minute", "days_of_week", "execution_budget_seconds"}
    clean = {key: value for key, value in schedule.items() if key in allowed and
             (value is None or isinstance(value, (str, int, float, bool)))}
    return clean or {"type": schedule_type}


def catalogue(user):
    now = timezone.now()
    rows = []
    for key, value in settings.CELERY_BEAT_SCHEDULE.items():
        rows.append(dict(id="beat:" + key, name=BEAT_NAMES.get(key, key), source="beat", module="系统",
            schedule=str(value["schedule"]), timezone=str(settings.CELERY_TIMEZONE),
            enabled=None, state="unknown", observed_at=None, stale=True,
            next_run_at=None, last_result=None, business_url=None))
    latest = SyncRun.objects.filter(sync_job_id=OuterRef("pk")).order_by("-pk")
    jobs = SyncJob.objects.filter(tenant_id=user.tenant_id).select_related("integration_config").annotate(
        latest_result=Subquery(latest.values("status")[:1]))
    if jobs.count() > 10000:
        raise ValidationError("当前租户任务超过目录查询上限，请使用同步任务菜单查询")
    for job in jobs.order_by("pk").iterator(chunk_size=200):
        rows.append(dict(id=f"sync:{job.pk}", name=f"{job.integration_config.platform} · {job.resource_type} #{job.pk}",
            source="sync_job", module=job.integration_config.platform,
            schedule=json.dumps(safe_sync_schedule(job.sync_scope, job.schedule_type), ensure_ascii=False), timezone=safe_sync_schedule(job.sync_scope, job.schedule_type).get("timezone"), enabled=job.is_enabled,
            state=job.status, observed_at=now, stale=False, next_run_at=job.next_run_at,
            last_result=job.latest_result, business_url="/integrations/sync-jobs"))
    plans = Plan.objects.filter(tenant_id=user.tenant_id, deleted_at__isnull=True) if Plan else None
    if plans is not None and plans.count() > 10000:
        raise ValidationError("当前租户闪购计划超过目录查询上限")
    for plan in (plans.order_by("pk").iterator(chunk_size=200) if plans is not None else []):
        rows.append(dict(id=f"flash:{plan.pk}", name=plan.name, source="flash", module="闪购",
            schedule=f"{plan.kind} {plan.local_time}", timezone="Asia/Shanghai", enabled=plan.enabled,
            state="idle" if plan.enabled else "paused", observed_at=now, stale=False,
            next_run_at=plan.next_due, last_result=None, business_url="/integrations/sync-jobs?workspace=flash"))
    observed = observations()
    known = {row["id"] for row in rows}
    for key, item in observed.items():
        if key.startswith("beat:") and key not in known:
            rows.append(dict(id=key, name=BEAT_NAMES.get(key[5:], key[5:]), source="beat",
                module="系统", schedule=item.get("schedule"), timezone="UTC",
                enabled=None, state="unknown", observed_at=None, stale=True,
                next_run_at=None, last_result=None, business_url=None))
    for key, (name, source) in EXTERNAL.items():
        item = observed.get(key, {})
        stamp = parse_datetime(item.get("observed_at", "")) if item else None
        stale = not stamp or timezone.is_naive(stamp) or stamp < now - timedelta(minutes=15)
        rows.append(dict(id="external:" + key, name=name, source=source, module="系统",
            schedule=item.get("schedule"), timezone="Asia/Shanghai",
            enabled=item.get("enabled"), state="unknown" if stale else item.get("state", "unknown"),
            observed_at=stamp, stale=stale, next_run_at=item.get("next_run_at"),
            last_result=None if key in {"abc", "replenishment", "inventory_warnings"} else item.get("last_result"), business_url=None))
    observed = observations()
    for row in rows:
        item = observed.get(row["id"]) if row["source"] == "beat" else None
        if item:
            stamp = parse_datetime(item["observed_at"])
            stale = stamp < now - timedelta(minutes=15)
            row.update(schedule=item.get("schedule") or row["schedule"], enabled=item["enabled"], observed_at=stamp, stale=stale,
                state="unknown" if stale else item["state"], next_run_at=item.get("next_run_at"),
                last_result=item.get("last_result"))
    return rows

def paginate(request, rows):
    try:
        page = int(request.query_params.get("page", 1))
        size = int(request.query_params.get("page_size", 20))
    except ValueError:
        raise ValidationError("分页参数无效")
    if page < 1 or not 1 <= size <= 100:
        raise ValidationError("分页参数超出范围")
    paginator = Paginator(rows, size)
    if page > paginator.num_pages:
        raise NotFound()
    return dict(count=paginator.count, results=list(paginator.page(page)), page=page, page_size=size)

class AutomationBase(APIView):
    permission_classes = [InternalSuperuserPermission]

class TaskList(AutomationBase):
    def get(self, request):
        rows = catalogue(request.user)
        source = request.query_params.get("source")
        search = request.query_params.get("search", "")[:200].lower()
        rows = [row for row in rows if (not source or row["source"] == source) and search in row["name"].lower()]
        return success_response(paginate(request, rows))

class Overview(AutomationBase):
    def get(self, request):
        rows = catalogue(request.user)
        return success_response(dict(total=len(rows),
            enabled=sum(row["enabled"] is True for row in rows),
            paused=sum(row["enabled"] is False for row in rows),
            running=sum(row["state"] == "running" for row in rows),
            failed=sum(row["state"] == "failed" for row in rows),
            unknown=sum(row["state"] == "unknown" for row in rows),
            stale=sum(row["stale"] for row in rows)))

class TaskDetail(AutomationBase):
    def get(self, request, task_id):
        item = next((row for row in catalogue(request.user) if row["id"] == task_id), None)
        if item is None:
            raise NotFound()
        return success_response(item)

class RunList(AutomationBase):
    def get(self, request):
        task_id = request.query_params.get("task_id", "")
        source = request.query_params.get("source", "")
        search = request.query_params.get("search", "")[:200].lower()
        runs = SyncRun.objects.filter(tenant_id=request.user.tenant_id).select_related("sync_job__integration_config")
        batches = Batch.objects.filter(tenant_id=request.user.tenant_id).select_related("plan") if Batch else None
        if task_id.startswith("sync:"):
            identifier = task_id[5:]
            if not identifier.isascii() or not identifier.isdigit() or len(identifier) > 18 or int(identifier) < 1:
                raise ValidationError("同步任务编号无效")
        if task_id:
            if task_id.startswith("sync:"):
                runs = runs.filter(sync_job_id=int(task_id[5:]))
                batches = batches.none() if batches is not None else None
            elif task_id.startswith("flash:"):
                try:
                    plan_id = UUID(task_id[6:])
                except ValueError:
                    raise ValidationError("闪购计划编号无效")
                batches = batches.filter(plan_id=plan_id) if batches is not None else None
                runs = runs.none()
            else:
                runs, batches = runs.none(), batches.none() if batches is not None else None
        if source:
            if source != "sync_job":
                runs = runs.none()
            if source != "flash":
                batches = batches.none() if batches is not None else None
        # Explicit bounded recent history prevents a catalogue request scanning all historical logs.
        items = []
        for run in runs.order_by("-pk")[:1000]:
            name = f"{run.sync_job.integration_config.platform} · {run.sync_job.resource_type} #{run.sync_job_id}"
            if search not in name.lower():
                continue
            items.append(dict(id=f"sync-run:{run.pk}", task_id=f"sync:{run.sync_job_id}", name=name,
                source="sync_job", status=run.status, started_at=run.started_at, finished_at=run.finished_at,
                result=f"处理 {run.fetched_count}，失败 {run.failed_count}" + (f"，{run.error_code}" if run.error_code else "")))
        for batch in (batches.order_by("-created_at")[:1000] if batches is not None else []):
            name = batch.plan.name if batch.plan_id else "闪购临时批次"
            if search not in name.lower():
                continue
            items.append(dict(id=f"flash-run:{batch.pk}", task_id=f"flash:{batch.plan_id}" if batch.plan_id else None,
                name=name, source="flash", status="finished" if batch.finished_at else "pending",
                started_at=batch.created_at, finished_at=batch.finished_at, result="批次已结束" if batch.finished_at else "批次待结束"))
        observed = observations()
        tasks = {row["id"]: row for row in catalogue(request.user)} if observed else {}
        for key, observation in observed.items():
            canonical = key if key.startswith("beat:") else "external:" + key
            task = tasks.get(canonical)
            if not task or (task_id and canonical != task_id) or (source and task["source"] != source) or search not in task["name"].lower():
                continue
            for run in observation.get("runs", []):
                if key in {"abc", "replenishment", "inventory_warnings"} and run.get("tenant_id") != request.user.tenant_id:
                    continue
                if run.get("tenant_id") is not None and run["tenant_id"] != request.user.tenant_id:
                    continue
                items.append(dict(id=canonical + ":" + run["id"], task_id=canonical,
                    name=task["name"], source=task["source"], status=run["status"],
                    started_at=parse_datetime(run["started_at"]) if run["started_at"] else None,
                    finished_at=parse_datetime(run["finished_at"]) if run["finished_at"] else None,
                    result=run["result"]))
        floor = timezone.datetime.min.replace(tzinfo=timezone.get_current_timezone())
        items.sort(key=lambda item: (item["started_at"] or item["finished_at"] or floor, item["id"]), reverse=True)
        data = paginate(request, items)
        data["history_limit_per_source"] = 1000
        return success_response(data)
