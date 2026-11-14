"""Durable, stepwise execution. HTTP writes are journaled before transmission."""
import time
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .domain import TERMINAL, digest, item_bodies, reconcile, retry_delay, validate_items
from .models import Activity, Batch, ExecutionPool, Intent, Preview, StoreConfig, StoreLock, StoreTask, WriteOperation
from .permissions import require_stores
from .provider import Deferred, Rejected, ShopeeAdapter, UnknownWrite, rejections
from .services import authorized_store


class LeaseLost(Exception):
    pass


class StopRequested(Exception):
    pass


def claim(task_id, *, now=None):
    # Commit singleton creation before requesting its exclusive lock. Concurrent
    # duplicate INSERTs must not retain shared locks and then deadlock on upgrade.
    ExecutionPool.objects.get_or_create(key="shopee")
    return _claim(task_id, now=now)


@transaction.atomic
def _claim(task_id, *, now=None):
    now = now or timezone.now()
    ExecutionPool.objects.select_for_update().get(key="shopee")
    task = StoreTask.objects.select_for_update().get(pk=task_id)
    if task.state.get("migration_hold") or task.state.get("retry_paused"):
        return None
    if task.status in TERMINAL or (task.lease_until and task.lease_until > now) or (task.next_attempt_at and task.next_attempt_at > now):
        return None
    if StoreTask.objects.filter(lease_until__gt=now).count() >= 3:
        return None
    StoreLock.objects.get_or_create(tenant_id=task.tenant_id, store_id=task.store_id)
    lock = StoreLock.objects.select_for_update().get(store_id=task.store_id)
    if lock.task_id and lock.task_id != task.id:
        return None
    lock.task = task
    lock.save(update_fields=["task", "updated_at"])
    if task.status in {"waiting", "confirming"}:
        task.waiting_ms += max(0, int((now - task.updated_at).total_seconds() * 1000))
    task.fence, task.lease_until = uuid.uuid4(), now + timedelta(minutes=3)
    task.status, task.started_at = "running", task.started_at or now
    task.save(update_fields=["fence", "lease_until", "status", "started_at", "waiting_ms", "updated_at"])
    return task


def fence(task, *, allow_stopped=False):
    current = StoreTask.objects.select_related("batch", "batch__actor").get(pk=task.id)
    if current.fence != task.fence or not current.lease_until or current.lease_until <= timezone.now():
        raise LeaseLost()
    require_stores(current.batch.actor, [current.store_id], "delete" if current.batch.operation == "delete" else "execute")
    if current.batch.stop_requested and not allow_stopped:
        raise StopRequested()
    return current


def save_state(task):
    if not StoreTask.objects.filter(pk=task.id, fence=task.fence).update(state=task.state, completed=task.completed):
        raise LeaseLost()


def write_once(task, intent, key, endpoint, payload, adapter):
    with transaction.atomic():
        StoreTask.objects.select_for_update().get(pk=task.id)
        fence(task, allow_stopped=key == "cleanup")
        operation, _ = WriteOperation.objects.get_or_create(tenant_id=task.tenant_id, intent=intent, key=key,
            defaults={"endpoint": endpoint, "payload": payload})
        if operation.endpoint != endpoint or operation.payload != payload:
            raise ValidationError("原写入意图不能更换参数。")
        if operation.status in {"returned", "confirmed"}:
            return operation.response
        if operation.status == "rejected":
            raise Rejected(operation.response.get("code", "rejected"))
        if operation.status == "submitted":
            raise UnknownWrite("原写入尚未确认，先回读，不重复提交")
        operation.status, operation.submitted_at = "submitted", timezone.now()
        operation.save(update_fields=["status", "submitted_at", "updated_at"])
    try:
        if isinstance(adapter, ShopeeAdapter):
            adapter.write_guard = lambda: fence(task, allow_stopped=key == "cleanup")
        result = adapter.call(endpoint, body=payload)
    except UnknownWrite:
        raise
    except Deferred:
        WriteOperation.objects.filter(pk=operation.id, status="submitted").update(status="prepared")
        raise
    except (PermissionDenied, ValidationError, StopRequested, LeaseLost):
        # These exceptions come from the adapter's preflight/guard before HTTP.
        WriteOperation.objects.filter(pk=operation.id, status="submitted").update(status="prepared")
        raise
    except Rejected as exc:
        WriteOperation.objects.filter(pk=operation.id).update(status="rejected", response={"code": exc.code})
        raise
    except Exception:
        raise UnknownWrite("写入结果未知，继续回读核对") from None
    response = {key: result[key] for key in ("flash_sale_id", "status") if isinstance(result, dict) and key in result}
    response["rejections"] = rejections(result)
    WriteOperation.objects.filter(pk=operation.id).update(status="returned", response=response)
    fence(task, allow_stopped=True)
    return response


def sync_cache(task, adapter):
    fence(task)
    selected = task.snapshot.get("activity_ids", [])
    if selected:
        for activity_id in selected:
            fence(task)
            detail = adapter.detail(activity_id)
            if not detail:
                raise ValidationError("活动已不存在，保留历史缓存等待核对。")
            items = adapter.items(activity_id)
            fence(task)
            Activity.objects.filter(tenant_id=task.tenant_id, store_id=task.store_id, platform_id=activity_id).update(
                items=items, platform_status=detail["status"], details_synced_at=timezone.now(),
                synced_at=timezone.now(), item_count=len({row["item_id"] for row in items}),
                enabled_count=len({row["item_id"] for row in items if row.get("status") == 1}))
        return "succeeded", "所选活动已同步"
    rows = adapter.activities()
    fence(task)
    now = timezone.now()
    with transaction.atomic():
        for row in rows:
            Activity.objects.update_or_create(tenant_id=task.tenant_id, store_id=task.store_id,
                platform_id=str(row["flash_sale_id"]), defaults={
                    "slot_id": str(row["timeslot_id"]), "starts_at": datetime.fromtimestamp(row["start_time"], dt_timezone.utc),
                    "ends_at": datetime.fromtimestamp(row["end_time"], dt_timezone.utc), "platform_status": row["status"],
                    "item_count": row.get("item_count"), "enabled_count": row.get("enabled_item_count"), "synced_at": now})
        StoreConfig.objects.filter(store_id=task.store_id, tenant_id=task.tenant_id).update(last_synced_at=now)
    return "succeeded", "活动已同步"


def prepare_intent(task, adapter):
    fence(task)
    if task.batch.operation == "copy":
        preview = Preview.objects.get(pk=task.snapshot["preview_id"], tenant_id=task.tenant_id, store_id=task.store_id, batch=task.batch)
        if preview.expires_at <= timezone.now():
            raise ValidationError("预览已过期，请重新预览。")
        source = adapter.items(preview.source_id)
        if digest(source) != preview.source_hash:
            raise ValidationError("来源活动已变化，请重新预览。")
        target, items, source_id = preview.target, preview.items, preview.source_id
    else:
        activities = sorted(adapter.activities(), key=lambda row: row["start_time"], reverse=True)
        source, source_id = [], ""
        for activity in activities:
            fence(task)
            source = adapter.items(str(activity["flash_sale_id"]))
            if source:
                source_id = str(activity["flash_sale_id"])
                break
        if not source:
            raise ValidationError("没有包含商品的来源活动。")
        items = validate_items([{key: row[key] for key in ("item_id", "model_id", "price", "purchase_limit")}
                                | {"stock": task.snapshot["stock"]} for row in source])
        occupied = {str(row["timeslot_id"]) for row in activities if row.get("status") != 0}
        occupied.update(Intent.objects.filter(tenant_id=task.tenant_id, store_id=task.store_id, reservation_key__isnull=False).values_list("slot_id", flat=True))
        targets = [row for row in adapter.slots() if str(row["timeslot_id"]) not in occupied
                   and row["start_time"] > time.time() + 600]
        if not targets:
            raise ValidationError("没有可用的后续时段。")
        target = min(targets, key=lambda row: row["start_time"])
    fence(task)
    if target["start_time"] <= time.time() + 600:
        raise ValidationError("目标时段临近开始，请重新选择。")
    if any(str(row["timeslot_id"]) == str(target["timeslot_id"]) and row.get("status") != 0 for row in adapter.activities()):
        raise ValidationError("目标时段已有活动，不能重复创建。")
    return Intent.objects.create(tenant_id=task.tenant_id, task=task, store_id=task.store_id,
        slot_id=str(target["timeslot_id"]), reservation_key=f"{task.tenant_id}:{task.store_id}:{target['timeslot_id']}", target=target, source_id=source_id, items=items)


def advance_create(task, intent, adapter):
    if intent.status == "cleaning":
        cleanup(task, intent, adapter, stopped=task.batch.stop_requested)
        return
    if not intent.platform_id:
        previous = intent.writes.filter(key="create", status="submitted").first()
        if previous:
            fence(task, allow_stopped=True)
            matches = [row for row in adapter.activities() if str(row["timeslot_id"]) == intent.slot_id and row.get("status") != 0]
            if len(matches) != 1:
                raise UnknownWrite("创建结果尚未确认，保留时段占用，禁止再次创建")
            intent.platform_id = str(matches[0]["flash_sale_id"])
            intent.result["create_recovery"] = {"slot_id": intent.slot_id, "platform_id": intent.platform_id,
                "intent_id": intent.id, "store_id": task.store_id, "tenant_id": task.tenant_id}
            # A matching slot is sufficient for continued readback, but not proof
            # that this worker may delete an activity without its create receipt.
            intent.owns_activity = False
            previous.status, previous.readback = "confirmed", intent.result["create_recovery"]
            previous.response = {"flash_sale_id": intent.platform_id}
            previous.save(update_fields=["status", "readback", "response", "updated_at"])
        else:
            result = write_once(task, intent, "create", "create_shop_flash_sale", {"timeslot_id": int(intent.slot_id)}, adapter)
            if not result.get("flash_sale_id"):
                intent.writes.filter(key="create").update(status="submitted")
                raise UnknownWrite("创建响应缺少活动编号")
            intent.platform_id, intent.owns_activity = str(result["flash_sale_id"]), True
        intent.status = "adding"
        intent.save(update_fields=["platform_id", "owns_activity", "status", "result", "updated_at"])
        return
    if task.batch.stop_requested:
        cleanup(task, intent, adapter, stopped=True)
        return
    if not intent.owns_activity:
        # A slot match alone cannot authorize writing into an activity created elsewhere.
        results = reconcile(intent.items, adapter.items(intent.platform_id), [])
        detail = adapter.detail(intent.platform_id)
        if results and all(row["state"] == "enabled" for row in results) and detail and detail.get("status") == 1:
            intent.status = "succeeded"
            intent.result.update(specifications=results, enabled_count=len(results))
            intent.save(update_fields=["status", "result", "updated_at"])
            return
        raise UnknownWrite("目标时段活动已找到，但创建归属尚无回执证明；仅回读，不补写或删除")
    bodies = item_bodies(intent.items)
    for offset in range(0, len(bodies), 5):
        key = f"add:{offset}"
        operation = intent.writes.filter(key=key).first()
        if operation and operation.status in {"returned", "confirmed"}:
            continue
        if operation and operation.status == "submitted":
            actual = adapter.items(intent.platform_id)
            ids = {str(row["item_id"]) for row in bodies[offset:offset + 5]}
            planned = [row for row in intent.items if row["item_id"] in ids]
            results = reconcile(planned, actual, [])
            if any(row["state"] != "enabled" for row in results):
                raise UnknownWrite("商品写入结果尚未确认，不重复提交")
            operation.status, operation.readback = "confirmed", {"results": results}
            operation.save(update_fields=["status", "readback", "updated_at"])
        else:
            write_once(task, intent, key, "add_shop_flash_sale_items",
                       {"flash_sale_id": int(intent.platform_id), "items": bodies[offset:offset + 5]}, adapter)
        return
    actual = adapter.items(intent.platform_id)
    rejected = [row for op in intent.writes.order_by("id") for row in op.response.get("rejections", [])]
    results = reconcile(intent.items, actual, rejected)
    intent.result["specifications"] = results
    intent.save(update_fields=["result", "updated_at"])
    if any(row["state"] in {"unknown", "mismatch"} for row in results):
        raise UnknownWrite("仍有未确认或不一致规格，继续核对")
    stock_keys = {(row["item_id"], row["model_id"]) for row in rejected if row.get("stock_rejected")}
    current = {(row["item_id"], row["model_id"]): row for row in actual}
    for index, row in enumerate(intent.items):
        identity = row["item_id"], row["model_id"]
        actual_row = current.get(identity)
        if identity not in stock_keys or (actual_row and actual_row.get("status") == 1) or intent.writes.filter(key=f"adjust:{index}").exists():
            continue
        if actual_row is None:
            actual_row = next((value for value in adapter.items(intent.source_id) if (value["item_id"], value["model_id"]) == identity), None)
        available = actual_row.get("available_stock") if actual_row else None
        if type(available) is not int or available < 0:
            raise UnknownWrite("缺少当前可用库存，保留原记录等待核对")
        if available < 4:
            continue
        adjusted = {**row, "stock": available // 2}
        updating = identity in current
        if not updating and any(value["item_id"] == row["item_id"] for value in actual):
            raise UnknownWrite("已有商品缺少规格，需人工核对")
        intent.items[index] = adjusted
        intent.result.setdefault("adjustments", []).append({"item_id": row["item_id"], "model_id": row["model_id"],
            "before": row["stock"], "after": adjusted["stock"], "available": available})
        intent.save(update_fields=["items", "result", "updated_at"])
        write_once(task, intent, f"adjust:{index}", "update_shop_flash_sale_items" if updating else "add_shop_flash_sale_items",
            {"flash_sale_id": int(intent.platform_id), "items": item_bodies([adjusted], update=updating)}, adapter)
        return
    for operation in intent.writes.filter(status="submitted", endpoint__in={"add_shop_flash_sale_items", "update_shop_flash_sale_items"}):
        affected = {str(value["item_id"]) for value in operation.payload.get("items", [])}
        if all(value["state"] == "enabled" for value in results if value["item_id"] in affected):
            operation.status, operation.readback = "confirmed", {"results": results}
            operation.save(update_fields=["status", "readback", "updated_at"])
    unresolved = intent.writes.filter(status="submitted").exclude(key="enable").exists()
    if unresolved:
        raise UnknownWrite("库存调整结果未确认，继续核对")
    enabled = sum(row["state"] == "enabled" for row in results)
    if not enabled:
        cleanup(task, intent, adapter)
        return
    detail = adapter.detail(intent.platform_id)
    if not detail:
        raise UnknownWrite("活动详情尚未确认")
    if detail.get("status") != 1:
        write_once(task, intent, "enable", "update_shop_flash_sale", {"flash_sale_id": int(intent.platform_id), "status": 1}, adapter)
        if (adapter.detail(intent.platform_id) or {}).get("status") != 1:
            raise UnknownWrite("活动启用结果未确认")
    intent.status = "succeeded"
    intent.result["enabled_count"] = enabled
    intent.writes.filter(key="enable", status__in={"submitted", "returned"}).update(status="confirmed", readback={"status": 1})
    intent.save(update_fields=["status", "result", "updated_at"])


def cleanup(task, intent, adapter, *, stopped=False):
    intent.status = "cleaning"
    intent.save(update_fields=["status", "updated_at"])
    detail = adapter.detail(intent.platform_id)
    if detail and detail.get("status") != 0:
        if not intent.owns_activity or detail["start_time"] <= time.time():
            raise UnknownWrite("活动已开始或创建归属未确认，保留活动并等待人工核对")
        operation = intent.writes.filter(key="cleanup").first()
        if operation and operation.status == "submitted":
            raise UnknownWrite("清理结果未确认，继续回读，不重复删除")
        write_once(task, intent, "cleanup", "delete_shop_flash_sale", {"flash_sale_id": int(intent.platform_id)}, adapter)
        detail = adapter.detail(intent.platform_id)
    if detail and detail.get("status") != 0:
        raise UnknownWrite("平台尚未确认清理结果")
    intent.status = "failed"
    intent.absence_evidence = {"confirmed_at": timezone.now().isoformat(), "platform_id": intent.platform_id, "absent": True}
    intent.writes.filter(key="cleanup", status="submitted").update(status="confirmed", readback=intent.absence_evidence)
    intent.reservation_key = None
    intent.result["message"] = "已安全停止并清理本次空活动" if stopped else "没有可参加规格，本次新建活动已清理"
    intent.save(update_fields=["status", "absence_evidence", "reservation_key", "result", "updated_at"])


def advance_action(task, adapter):
    activity_id = task.snapshot["activity_id"]
    intent, _ = Intent.objects.get_or_create(tenant_id=task.tenant_id, store_id=task.store_id,
        slot_id=f"{task.batch.operation}:{activity_id}:{task.batch_id}",
        defaults={"task": task, "platform_id": activity_id})
    detail = adapter.detail(activity_id)
    deleting = task.batch.operation == "delete"
    submitted = intent.writes.filter(key="action", status="submitted").exists()
    if deleting and (not detail or detail.get("status") == 0):
        evidence = {"confirmed_at": timezone.now().isoformat(), "platform_id": activity_id, "absent": True}
        Intent.objects.filter(tenant_id=task.tenant_id, store_id=task.store_id, platform_id=activity_id).update(reservation_key=None, absence_evidence=evidence)
        intent.status, intent.result = "succeeded", {"message": "所选活动已确认删除"}
        intent.save(update_fields=["status", "result", "updated_at"])
        intent.writes.filter(key="action").update(status="confirmed", readback=evidence)
        return "succeeded", "已确认所选活动不存在或已删除"
    if not detail:
        raise ValidationError("所选活动不存在。")
    if not deleting and detail.get("status") == task.snapshot["desired_status"]:
        intent.status, intent.result = "succeeded", {"message": "活动状态已确认"}
        intent.save(update_fields=["status", "result", "updated_at"])
        intent.writes.filter(key="action").update(status="confirmed", readback={"status": detail["status"]})
        return "succeeded", "活动状态已确认"
    if submitted:
        raise UnknownWrite("活动操作结果未知，继续回读，不重复提交")
    if detail["start_time"] <= time.time():
        raise ValidationError("仅可操作尚未开始的活动。")
    endpoint = "delete_shop_flash_sale" if deleting else "update_shop_flash_sale"
    payload = {"flash_sale_id": int(activity_id)}
    if not deleting:
        payload["status"] = task.snapshot["desired_status"]
    write_once(task, intent, "action", endpoint, payload, adapter)
    return None


def step(task, adapter):
    current = fence(task, allow_stopped=True)
    task.batch.stop_requested = current.batch.stop_requested
    operation = task.batch.operation
    active = task.intents.exclude(status__in={"succeeded", "failed"}).first()
    if current.batch.stop_requested and not active:
        return "stopped", f"已安全停止，保留已完成 {task.completed}/{task.requested} 个时段"
    if current.batch.stop_requested and active and operation in {"toggle", "delete"} and not active.writes.exclude(status="prepared").exists():
        active.status, active.result = "failed", {"message": "已停止，尚未提交平台操作"}
        active.save(update_fields=["status", "result", "updated_at"])
        return "stopped", "已安全停止，未提交平台操作"
    if current.batch.stop_requested and active and not active.platform_id and not active.writes.filter(status="submitted").exists():
        active.status = "failed"
        active.reservation_key = None
        active.result = {"message": "已停止，尚未提交平台创建"}
        active.save(update_fields=["status", "reservation_key", "result", "updated_at"])
        return "stopped", f"已安全停止，保留已完成 {task.completed}/{task.requested} 个时段"
    authorized_store(task.store)
    if operation == "sync":
        return sync_cache(task, adapter)
    if operation in {"toggle", "delete"}:
        return advance_action(task, adapter)
    if not active:
        if task.completed >= task.requested:
            return "succeeded", f"已完成 {task.completed}/{task.requested} 个时段"
        active = prepare_intent(task, adapter)
    advance_create(task, active, adapter)
    if active.status == "succeeded":
        task.completed = task.intents.filter(status="succeeded").count()
        save_state(task)
    if active.status == "failed":
        return ("stopped" if current.batch.stop_requested else "failed"), f"已完成 {task.completed}/{task.requested}；{active.result.get('message', '本时段未完成')}"
    return None


def retry_progress(task):
    # Ignore leases, timestamps and retry messages; only business evidence is progress.
    intents = []
    for intent in task.intents.order_by("id").prefetch_related("writes"):
        specifications = [{"item_id": row.get("item_id"), "model_id": row.get("model_id"),
                           "state": row.get("state"), "readback": {
                               key: (row.get("readback") or {}).get(key) for key in ("status", "price", "stock")}}
                          for row in intent.result.get("specifications", [])]
        intents.append({"id": intent.id, "status": intent.status, "platform_id": intent.platform_id,
                        "owns_activity": intent.owns_activity, "specifications": specifications,
                        "adjustments": intent.result.get("adjustments", []),
                        "writes": [(row.key, row.status) for row in sorted(intent.writes.all(), key=lambda row: row.id)]})
    return digest({"completed": task.completed, "intents": intents})


def run_step(task_id, *, adapter=None):
    task = claim(task_id)
    if not task:
        return "not_claimed"
    start = time.monotonic()
    status, message, delay = "queued", "处理中", 0
    try:
        adapter = adapter or ShopeeAdapter(task.store)
        if isinstance(adapter, ShopeeAdapter):
            adapter.guard = lambda: fence(task, allow_stopped=task.batch.operation != "sync")
        outcome = step(task, adapter)
        if outcome:
            status, message = outcome
    except LeaseLost:
        return "lease_lost"
    except StopRequested:
        status, message = "queued", "正在安全停止并核对当前操作"
    except Deferred as exc:
        status, message = "confirming" if isinstance(exc, UnknownWrite) else "waiting", str(exc)
        delay = retry_delay(task.retry_count, exc.retry_after)
    except (PermissionDenied, ValidationError, Rejected) as exc:
        uncertain = task.intents.filter(writes__status="submitted").exists() or task.intents.exclude(platform_id="").exclude(status__in={"succeeded", "failed"}).exists()
        status = "confirming" if uncertain else "failed"
        message = "权限、授权或业务校验未通过；保留待核对记录" if uncertain else str(exc)[:500]
        delay = 300 if uncertain else 0
    except Exception:
        status, message, delay = "confirming", "处理未完成，保留记录等待核对", 300
    with transaction.atomic():
        current = StoreTask.objects.select_for_update().get(pk=task.id)
        if current.fence != task.fence:
            return "lease_lost"
        current.status, current.message, current.lease_until = status, message, None
        current.next_attempt_at = timezone.now() + timedelta(seconds=delay) if delay else None
        current.retry_count = task.retry_count + (1 if delay else 0)
        if current.batch.operation != "sync":
            progress = retry_progress(current)
            if delay:
                count = current.state.get("no_progress_count", 0) + 1 if current.state.get("retry_progress") == progress else 1
                current.state.update(retry_progress=progress, no_progress_count=count)
                if count >= 3:
                    current.state["retry_paused"] = True
                    current.state["retry_pause_reason"] = "连续 3 轮失败且无结果进展，已暂停自动核对；原任务与防重复保护保留。"
                    current.message = "自动核对已暂停：" + message
                    current.next_attempt_at = None
            else:
                current.state.update(retry_progress=progress, no_progress_count=0)
        current.execution_ms += max(0, int((time.monotonic() - start) * 1000))
        if status in TERMINAL:
            current.finished_at = timezone.now()
            StoreLock.objects.filter(task=current).update(task=None)
        current.save()
        batch = Batch.objects.select_for_update().get(pk=task.batch_id)
        if not batch.tasks.exclude(status__in=TERMINAL).exists():
            batch.finished_at = timezone.now()
            batch.save(update_fields=["finished_at", "updated_at"])
    return status
