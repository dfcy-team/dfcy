"""Durable, stepwise execution. HTTP writes are journaled before transmission."""
import time
import uuid
import random
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .domain import TERMINAL, digest, item_bodies, reconcile, retry_delay, validate_items
from .models import Activity, Batch, ExecutionPool, Intent, Notification, Preview, StoreConfig, StoreLock, StoreTask, WriteOperation
from .permissions import require_stores
from .provider import CredentialWait, Deferred, RateLimited, Rejected, SERVER_ERRORS, SharedCooldown, ShopeeAdapter, UnknownWrite, rejections
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
    if task.batch.operation == "sync" and not StoreLock.objects.filter(task_id=task.id).exists() and StoreTask.objects.exclude(batch__operation="sync").filter(
            status__in={"queued", "running", "waiting", "confirming"}).filter(
            Q(state__retry_paused=False) | Q(state__retry_paused__isnull=True),
            Q(state__migration_hold=False) | Q(state__migration_hold__isnull=True),
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)).exists():
        return None
    if StoreTask.objects.filter(lease_until__gt=now).count() >= 3:
        return None
    if StoreTask.objects.filter(store_id=task.store_id, lease_until__gt=now).exclude(pk=task.id).exists():
        return None
    StoreLock.objects.get_or_create(tenant_id=task.tenant_id, store_id=task.store_id)
    lock = StoreLock.objects.select_for_update().get(store_id=task.store_id)
    protected_read = (task.batch.operation == "sync" and lock.task_id and lock.task_id != task.id
        and lock.task.status in TERMINAL and lock.task.state.get("recovery_pending"))
    # Read-only cache refresh uses its own lease; never replace the write protection.
    if not protected_read and lock.task_id and lock.task_id != task.id:
        if lock.task.status in TERMINAL and lock.task.state.get("recovery_pending"):
            task.status, task.finished_at = "failed", now
            task.message = "前批次写入或清理尚未确认，店铺保护保留；本次未提交平台写入。"
            task.save(update_fields=["status", "finished_at", "message", "updated_at"])
            batch = Batch.objects.select_for_update().get(pk=task.batch_id)
            if not batch.tasks.exclude(status__in=TERMINAL).exists():
                batch.finished_at = now
                batch.save(update_fields=["finished_at", "updated_at"])
        return None
    if not protected_read:
        lock.task = task
        lock.save(update_fields=["task", "updated_at"])
    if task.status in {"waiting", "confirming"}:
        task.waiting_ms += max(0, int((now - task.updated_at).total_seconds() * 1000))
    task.fence, task.lease_until = uuid.uuid4(), now + timedelta(minutes=3)
    task.status, task.started_at = "running", task.started_at or now
    task.state["step_started_at"] = now.isoformat()
    task.save(update_fields=["fence", "lease_until", "status", "started_at", "waiting_ms", "state", "updated_at"])
    return task


def fence(task, *, allow_stopped=False):
    current = StoreTask.objects.select_related("batch", "batch__actor").get(pk=task.id)
    now = timezone.now()
    if current.fence != task.fence or not current.lease_until or current.lease_until <= now:
        raise LeaseLost()
    require_stores(current.batch.actor, [current.store_id], "delete" if current.batch.operation == "delete" else "execute")
    if current.batch.stop_requested and not allow_stopped:
        raise StopRequested()
    if current.lease_until <= now + timedelta(seconds=90):
        renewed_until = now + timedelta(minutes=3)
        if not StoreTask.objects.filter(pk=task.id, fence=task.fence, lease_until__gt=now).update(lease_until=renewed_until):
            raise LeaseLost()
        current.lease_until = renewed_until
    return current


def save_state(task):
    if not StoreTask.objects.filter(pk=task.id, fence=task.fence).update(state=task.state, completed=task.completed):
        raise LeaseLost()


def write_once(task, intent, key, endpoint, payload, adapter):
    if task.batch.operation == "sync":
        raise PermissionDenied("同步任务仅允许读取平台，不允许提交写入。")
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
    if isinstance(adapter, ShopeeAdapter):
        adapter.read_checkpoint = task.state.setdefault("sync_read_checkpoint", {})
        adapter.save_read_checkpoint = lambda: save_state(task)
    def progress(message):
        fence(task)
        task.state["sync_progress"] = message
        save_state(task)

    progress("正在准备同步")
    selected = task.snapshot.get("activity_ids", [])
    if task.snapshot.get("sync_scope") == "selected" and not selected:
        return "succeeded", "该店铺没有所选活动，无需同步"
    if task.batch.source == "post_sync":
        if not selected and task.snapshot.get("sync_scope") != "affected":
            parent = StoreTask.objects.filter(tenant_id=task.tenant_id, store_id=task.store_id,
                state__post_sync_task_id=task.id).first()
            if parent is None:
                raise ValidationError("缺少执行后同步的原任务，未进行全量读取。")
            selected = list(parent.intents.exclude(platform_id="").values_list("platform_id", flat=True).distinct())
        if not selected:
            return "succeeded", "未涉及平台活动，无需同步"
    if selected:
        for index, activity_id in enumerate(selected):
            progress(f"正在同步活动详情：{index + 1}/{len(selected)}")
            fence(task)
            detail = adapter.detail(activity_id)
            if task.batch.source == "post_sync" and (not detail or detail.get("status") == 0):
                Activity.objects.filter(tenant_id=task.tenant_id, store_id=task.store_id, platform_id=activity_id).update(
                    platform_status=0, items=[], item_count=0, enabled_count=0, synced_at=timezone.now(), details_synced_at=timezone.now())
                continue
            if not detail:
                raise ValidationError("活动已不存在，保留历史缓存等待核对。")
            items = adapter.items(activity_id)
            fence(task)
            Activity.objects.update_or_create(tenant_id=task.tenant_id, store_id=task.store_id, platform_id=activity_id,
                defaults=dict(slot_id=str(detail["timeslot_id"]), starts_at=datetime.fromtimestamp(detail["start_time"], dt_timezone.utc),
                ends_at=datetime.fromtimestamp(detail["end_time"], dt_timezone.utc),
                items=items, platform_status=detail["status"], details_synced_at=timezone.now(),
                synced_at=timezone.now(), item_count=len({row["item_id"] for row in items}),
                enabled_count=len({row["item_id"] for row in items if row.get("status") == 1})))
        return "succeeded", "所选活动已同步"
    adapter.progress = progress
    progress("正在读取活动列表")
    history = task.snapshot.get("sync_scope") == "history"
    rows = adapter.activities(window=task.snapshot.get("sync_window"), kinds=(3,) if history else (1, 2))
    fence(task)
    progress(f"正在保存 {len(rows)} 条活动记录")
    now = timezone.now()
    retired = 0
    with transaction.atomic():
        for row in rows:
            Activity.objects.update_or_create(tenant_id=task.tenant_id, store_id=task.store_id,
                platform_id=str(row["flash_sale_id"]), defaults={
                    "slot_id": str(row["timeslot_id"]), "starts_at": datetime.fromtimestamp(row["start_time"], dt_timezone.utc),
                    "ends_at": datetime.fromtimestamp(row["end_time"], dt_timezone.utc), "platform_status": row["status"],
                    "item_count": row.get("item_count"), "enabled_count": row.get("enabled_item_count"), "synced_at": now})
        if not history:
            # Only the complete current/future response can retire stale overview rows.
            # Preserve historical rows and product detail; this makes no platform write.
            retired = Activity.objects.filter(tenant_id=task.tenant_id, store_id=task.store_id,
                ends_at__gt=now).exclude(platform_status=0).exclude(
                platform_id__in=[str(row["flash_sale_id"]) for row in rows]).update(platform_status=0, synced_at=now)
            StoreConfig.objects.filter(store_id=task.store_id, tenant_id=task.tenant_id).update(last_synced_at=now)
    message = "所选日期范围的历史活动已同步" if history else "当前及未来活动已同步"
    if retired:
        message += f"；已移除 {retired} 条平台不再返回的当前/未来活动缓存"
    return "succeeded", message


def prepare_intent(task, adapter, source_intent=None):
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
        checkpoint = task.state.setdefault("source_search", {})
        if source_intent is None:
            source, source_id = [], ""
            for activity in adapter.candidate_activities(checkpoint, lambda: save_state(task)):
                fence(task)
                source = adapter.items(str(activity["flash_sale_id"]))
                if source:
                    source_id = str(activity["flash_sale_id"])
                    break
            if not source:
                raise ValidationError("没有包含商品的来源活动。")
            items = validate_items([{key: row[key] for key in ("item_id", "model_id", "price", "purchase_limit")}
                                    | {"stock": task.snapshot["stock"]} for row in source])
            source_intent = Intent.objects.create(tenant_id=task.tenant_id, task=task, store_id=task.store_id,
                slot_id="", source_id=source_id, items=items, status="selecting")
        else:
            items, source_id = source_intent.items, source_intent.source_id
        activities = checkpoint.get("active", [])
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
    if any(str(row["timeslot_id"]) == str(target["timeslot_id"]) and row.get("status") != 0
           for row in adapter.activities(window=(target["start_time"] - 1, target["end_time"] + 1), kinds=(1, 2))):
        raise ValidationError("目标时段已有活动，不能重复创建。")
    if source_intent is not None:
        source_intent.slot_id, source_intent.target = str(target["timeslot_id"]), target
        source_intent.reservation_key = f"{task.tenant_id}:{task.store_id}:{target['timeslot_id']}"
        source_intent.status = "prepared"
        source_intent.save(update_fields=["slot_id", "target", "reservation_key", "status", "updated_at"])
        return source_intent
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
            matches = [row for row in adapter.activities(window=(intent.target["start_time"] - 1, intent.target["end_time"] + 1))
                       if str(row["timeslot_id"]) == intent.slot_id and row.get("status") != 0]
            if not matches:
                # Each observation requires all activity types and complete pagination.
                # Keep the original reservation until separated readbacks agree.
                probe = intent.result.setdefault("create_absence_checks", {"count": 0, "last_at": 0})
                now = time.time()
                if now - probe["last_at"] >= 8:
                    probe.update(count=probe["count"] + 1, last_at=now)
                if probe["count"] >= 3:
                    intent.status, intent.reservation_key = "failed", None
                    intent.absence_evidence = {"absent": True, "confirmed_at": timezone.now().isoformat(),
                        "window": [intent.target["start_time"] - 1, intent.target["end_time"] + 1],
                        "complete_list_checks": probe["count"]}
                    intent.result["message"] = "连续完整回读确认原目标时段没有活动，无需删除；按原时段重试。"
                    previous.status, previous.readback = "confirmed", intent.absence_evidence
                    previous.save(update_fields=["status", "readback", "updated_at"])
                intent.save(update_fields=["status", "reservation_key", "absence_evidence", "result", "updated_at"])
                if intent.status == "failed":
                    return
            elif intent.result.pop("create_absence_checks", None):
                intent.save(update_fields=["result", "updated_at"])
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
            if intent.target["start_time"] <= time.time() + 600:
                raise ValidationError("目标时段临近开始，未提交新建。")
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
        intent.result.update(specifications=results, activity_status=detail.get("status") if detail else None)
        intent.save(update_fields=["result", "updated_at"])
        raise UnknownWrite("目标时段活动已找到，但创建归属尚无回执证明；仅回读，不补写或删除")
    if intent.target["start_time"] <= time.time():
        raise ValidationError("目标时段已开始，未继续提交商品或启用写入。")
    bodies = item_bodies(intent.items)
    writes = {operation.key: operation for operation in intent.writes.all()}
    for offset in range(0, len(bodies), 5):
        key = f"add:{offset}"
        operation = writes.get(key)
        if operation and operation.status in {"returned", "confirmed"}:
            continue
        if operation and (operation.status == "submitted" or
                          (operation.status == "rejected" and operation.response.get("code") in SERVER_ERRORS)):
            actual = adapter.items(intent.platform_id)
            ids = {str(row["item_id"]) for row in bodies[offset:offset + 5]}
            planned = [row for row in intent.items if row["item_id"] in ids]
            results = reconcile(planned, actual, [])
            intent.result["specifications"] = reconcile(intent.items, actual,
                [row for op in writes.values() for row in op.response.get("rejections", [])])
            intent.result["readback_scope"] = {"group_offset": offset, "group_specifications": len(planned),
                "planned_specifications": len(intent.items)}
            intent.save(update_fields=["result", "updated_at"])
            if any(row["state"] != "enabled" for row in results):
                enabled = sum(row["state"] == "enabled" for row in results)
                raise UnknownWrite(f"本组商品写入已确认 {enabled}/{len(results)} 个规格（目标共 {len(intent.items)} 个规格），其余待核对；不重复提交原组商品")
            operation.status, operation.readback = "confirmed", {"results": results}
            operation.save(update_fields=["status", "readback", "updated_at"])
        else:
            write_once(task, intent, key, "add_shop_flash_sale_items",
                       {"flash_sale_id": int(intent.platform_id), "items": bodies[offset:offset + 5]}, adapter)
        return
    for operation in writes.values():
        if operation.key.startswith("adjust:") and operation.status == "prepared":
            write_once(task, intent, operation.key, operation.endpoint, operation.payload, adapter)
            return
    actual = adapter.items(intent.platform_id)
    rejected = [row for op in sorted(writes.values(), key=lambda op: op.id) for row in op.response.get("rejections", [])]
    results = reconcile(intent.items, actual, rejected)
    intent.result["specifications"] = results
    intent.save(update_fields=["result", "updated_at"])
    if any(row["state"] in {"unknown", "mismatch"} for row in results):
        raise UnknownWrite("仍有未确认或不一致规格，继续核对")
    stock_keys = {(row["item_id"], row["model_id"]) for row in rejected if row.get("stock_rejected")}
    current = {(row["item_id"], row["model_id"]): row for row in actual}
    source_stock = None
    adjusted_identities = {(row["item_id"], row["model_id"]) for row in intent.result.get("adjustments", [])}
    adjustments = []
    adjustment_mode = None
    for index, row in enumerate(intent.items):
        identity = row["item_id"], row["model_id"]
        actual_row = current.get(identity)
        if identity not in stock_keys or (actual_row and actual_row.get("status") == 1) or f"adjust:{index}" in writes or identity in adjusted_identities:
            continue
        if actual_row is None:
            if source_stock is None:
                source_stock = {(value["item_id"], value["model_id"]): value for value in adapter.items(intent.source_id)}
            actual_row = source_stock.get(identity)
        available = actual_row.get("available_stock") if actual_row else None
        if type(available) is not int or available < 0:
            raise UnknownWrite("缺少当前可用库存，保留原记录等待核对")
        if available < 4:
            continue
        adjusted = {**row, "stock": available // 2}
        updating = identity in current
        if not updating and any(value["item_id"] == row["item_id"] for value in actual):
            raise UnknownWrite("已有商品缺少规格，需人工核对")
        if adjustment_mode is not None and updating != adjustment_mode:
            continue
        if len({value[1]["item_id"] for value in adjustments} | {row["item_id"]}) > 5:
            continue
        adjustment_mode = updating
        adjustments.append((index, adjusted, available))
    if adjustments:
        for index, adjusted, available in adjustments:
            row = intent.items[index]
            intent.result.setdefault("adjustments", []).append({"item_id": row["item_id"], "model_id": row["model_id"],
                "before": row["stock"], "after": adjusted["stock"], "available": available})
            intent.items[index] = adjusted
        intent.save(update_fields=["items", "result", "updated_at"])
        write_once(task, intent, f"adjust:{adjustments[0][0]}", "update_shop_flash_sale_items" if adjustment_mode else "add_shop_flash_sale_items",
            {"flash_sale_id": int(intent.platform_id), "items": item_bodies([value[1] for value in adjustments], update=adjustment_mode)}, adapter)
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
        if (str(detail.get("timeslot_id")) != intent.slot_id
                or detail.get("start_time") != intent.target.get("start_time")
                or detail.get("end_time") != intent.target.get("end_time")):
            raise UnknownWrite("目标活动时段与原意图不一致，禁止清理")
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
    intent.result["message"] = ("已安全停止并清理本次活动" if stopped else
        "本次失败，目标活动已清理：" + intent.result["failure_reason"] if intent.result.get("failure_reason") else
        "没有可参加规格，本次新建活动已清理")
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
    elif active.status == "selecting":
        active = prepare_intent(task, adapter, source_intent=active)
    advance_create(task, active, adapter)
    if active.status == "succeeded":
        task.completed = task.intents.filter(status="succeeded").count()
        save_state(task)
    if active.status == "failed":
        if not current.batch.stop_requested and task.batch.operation in {"run", "copy"}:
            attempt = active.result.get("execution_attempt", 0)
            if attempt < 3 and active.absence_evidence.get("absent") and active.target["start_time"] > time.time() + 600:
                Intent.objects.create(tenant_id=task.tenant_id, task=task, store_id=task.store_id,
                    slot_id=active.slot_id, reservation_key=f"{task.tenant_id}:{task.store_id}:{active.slot_id}",
                    target=active.target, source_id=active.source_id, items=active.items,
                    result={"execution_attempt": attempt + 1})
                return "queued", f"目标活动已清理，开始第 {attempt + 1}/3 次重试"
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
    shared_cooldown = False
    read_failure = False
    cleanup_reason = None
    recovery_error = None
    credential_wait = None
    try:
        adapter = adapter or ShopeeAdapter(task.store)
        if isinstance(adapter, ShopeeAdapter):
            adapter.task_id = task.id
            adapter.guard = lambda: fence(task, allow_stopped=task.batch.operation != "sync")
        outcome = step(task, adapter)
        if outcome:
            status, message = outcome
    except LeaseLost:
        return "lease_lost"
    except StopRequested:
        status, message = "queued", "正在安全停止并核对当前操作"
    except Deferred as exc:
        recovery_error = exc
        status, message = "confirming" if isinstance(exc, UnknownWrite) else "waiting", str(exc)
        delay = retry_delay(task.retry_count, exc.retry_after)
        shared_cooldown = isinstance(exc, (SharedCooldown, RateLimited, CredentialWait))
        if isinstance(exc, CredentialWait):
            credential_wait = exc.code
        read_failure = not isinstance(exc, UnknownWrite)
        if exc.retry_after:
            delay += random.uniform(1, 15)
    except (PermissionDenied, ValidationError, Rejected) as exc:
        uncertain = task.intents.filter(writes__status="submitted").exists() or task.intents.exclude(platform_id="").exclude(status__in={"succeeded", "failed"}).exists()
        status = "confirming" if uncertain else "failed"
        reason = f"平台拒绝操作（{exc.code}）" if isinstance(exc, Rejected) else str(exc)[:350]
        message = reason + "；保留原活动等待核对" if uncertain else reason
        delay = 300 if uncertain else 0
        cleanup_reason = message
    except Exception as exc:
        # Persist only exception type and code location, never raw exception text or locals.
        trace = exc.__traceback__
        while trace.tb_next:
            trace = trace.tb_next
        location = f"{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}"
        status, message, delay = "confirming", f"处理异常（{type(exc).__name__}，{location}）；保留原记录等待核对", 300
        cleanup_reason = message
    with transaction.atomic():
        current = StoreTask.objects.select_for_update().get(pk=task.id)
        if current.fence != task.fence:
            return "lease_lost"
        if credential_wait:
            current.state["credential_wait"] = credential_wait
        else:
            current.state.pop("credential_wait", None)
        if cleanup_reason and current.batch.operation in {"run", "copy"}:
            active = current.intents.exclude(status__in={"succeeded", "failed"}).first()
            if active and active.owns_activity and active.platform_id and active.status != "cleaning":
                active.status = "cleaning"
                active.result["failure_reason"] = cleanup_reason
                active.save(update_fields=["status", "result", "updated_at"])
                status, message, delay = "queued", "本次未完成，先清理目标活动再重试；" + cleanup_reason, 0
        prewrite_read_failure = (read_failure and not shared_cooldown and current.batch.operation in {"run", "copy"}
            and not current.intents.exclude(platform_id="").exists()
            and not WriteOperation.objects.filter(intent__task=current).exclude(status="prepared").exists())
        if prewrite_read_failure:
            failures = current.state.get("prewrite_read_failures", 0) + 1
            current.state["prewrite_read_failures"] = failures
            if failures >= 4:
                status, delay = "failed", 0
                message = "创建前读取失败，3 次重试已耗尽；未提交平台写入，无需清理活动。原因：" + message
                current.state.update(retry_paused=False, retry_pause_reason="", no_progress_count=0)
                current.intents.update(status="failed", reservation_key=None,
                    absence_evidence={"absent": True, "not_submitted": True})
        current.status, current.message, current.lease_until = status, message, None
        current.next_attempt_at = timezone.now() + timedelta(seconds=delay) if delay else None
        current.retry_count = task.retry_count + (1 if delay and not shared_cooldown else 0)
        uncertain_rate_limit = (shared_cooldown
            and status == "waiting" and (current.intents.filter(writes__status="submitted").exists()
                or current.intents.exclude(platform_id="").exclude(status__in={"succeeded", "failed"}).exists())
            and isinstance(recovery_error, RateLimited))
        if current.batch.operation != "sync" and (not shared_cooldown or uncertain_rate_limit) and not prewrite_read_failure:
            progress = retry_progress(current)
            if delay:
                count = current.state.get("no_progress_count", 0) + 1 if current.state.get("retry_progress") == progress else 1
                current.state.update(retry_progress=progress, no_progress_count=count)
                current.state["verification_failures"] = current.state.get("verification_failures", 0) + 1
                if count >= 4:
                    active = current.intents.exclude(status__in={"succeeded", "failed"}).first()
                    can_clean = (active and current.batch.operation in {"run", "copy"}
                        and active.owns_activity and active.platform_id and active.status != "cleaning"
                        and active.target.get("start_time", 0) > time.time())
                    current.state.update(retry_paused=False, retry_pause_reason="", no_progress_count=0)
                    if can_clean:
                        active.status = "cleaning"
                        active.result["failure_reason"] = message
                        active.save(update_fields=["status", "result", "updated_at"])
                        status, message = "queued", "3 次核对重试后仍未完成，先核实并清理本系统目标活动，再决定重建。"
                    else:
                        status = "failed"
                        pending = bool(active and (active.platform_id or active.writes.exclude(status="prepared").exists()))
                        current.state["recovery_pending"] = pending
                        message = "3 次核对重试已耗尽；执行失败。" + message
                        if pending:
                            message += "；清理未确认，未重复写入或重建；店铺与时段保护保留，可只读核对。"
                        if active:
                            active.status = "failed"
                            active.result.update(message=message, cleanup_status="unconfirmed" if pending else "not_submitted")
                            if not pending:
                                active.reservation_key = None
                                active.absence_evidence = {"absent": True, "not_submitted": True}
                            active.save(update_fields=["status", "result", "reservation_key", "absence_evidence", "updated_at"])
                    current.status, current.message, current.next_attempt_at = status, message, None
            else:
                current.state.update(retry_progress=progress, no_progress_count=0)
        current.execution_ms += max(0, int((time.monotonic() - start) * 1000))
        if status in TERMINAL:
            if status == "failed" and not current.state.get("recovery_pending"):
                for intent in current.intents.exclude(status__in={"succeeded", "failed"}):
                    if not intent.platform_id and not intent.writes.exclude(status="prepared").exists():
                        intent.status, intent.reservation_key = "failed", None
                        intent.absence_evidence = {"absent": True, "not_submitted": True}
                        intent.save(update_fields=["status", "reservation_key", "absence_evidence", "updated_at"])
            current.finished_at = timezone.now()
            current.state.update(retry_paused=False, retry_pause_reason="")
            if not current.state.get("recovery_pending"):
                StoreLock.objects.filter(task=current).update(task=None)
        current.save()
        batch = Batch.objects.select_for_update().get(pk=task.batch_id)
        if not batch.tasks.exclude(status__in=TERMINAL).exists():
            batch.finished_at = timezone.now()
            batch.save(update_fields=["finished_at", "updated_at"])
    return status


@transaction.atomic
def recover_failed(task_id):
    """Continue the original exception flow without changing its slot or retry budget."""
    ExecutionPool.objects.select_for_update().get(key="shopee")
    requested = StoreTask.objects.get(pk=task_id)
    lock = StoreLock.objects.select_for_update().filter(
        tenant_id=requested.tenant_id, store_id=requested.store_id).first()
    if not lock or not lock.task_id:
        raise ValidationError("该店铺没有待处理的原任务保护。")
    task = StoreTask.objects.select_for_update().select_related("batch").get(pk=lock.task_id)
    if task.status not in TERMINAL and task.state.get("exception_recovery_round"):
        return task
    if (task.status != "failed" or not task.state.get("recovery_pending")
            or task.state.get("migration_hold") or task.batch.operation not in {"run", "copy"}
            or task.batch.stop_requested):
        raise ValidationError("原任务不能进入异常恢复流程，请查看原任务详情。")
    if StoreTask.objects.filter(store_id=task.store_id, lease_until__gt=timezone.now()).exists():
        raise ValidationError("该店铺仍有任务执行中，请稍后处理原任务。")
    intents = list(task.intents.filter(reservation_key__isnull=False).exclude(status="succeeded"))
    if len(intents) != 1:
        raise ValidationError("原目标时段记录不唯一，保留保护等待核对。")
    intent = intents[0]
    if intent.result.get("execution_attempt", 0) >= 3:
        raise ValidationError("原时段的 3 次重建重试已耗尽；只能核对清理结果，不能重置次数。")
    if intent.target.get("start_time", 0) <= time.time() + 600:
        raise ValidationError("原目标时段已开始或临近开始，不能重建；请核对清理结果。")
    # Do not race a notification sender or silently overwrite its unknown outcome.
    notifications = list(Notification.objects.select_for_update().filter(batch=task.batch))
    if any(n.lease_until or n.status in {"sending", "failed_or_unknown", "uncertain_expired"} for n in notifications):
        raise ValidationError("原批次通知正在发送或结果未确认，请先核对通知状态。")
    intent.status = "cleaning" if intent.owns_activity and intent.platform_id else "adding" if intent.platform_id else "prepared"
    intent.save(update_fields=["status", "updated_at"])
    task.state.update(recovery_pending=False, retry_paused=False, no_progress_count=0,
        exception_recovery_round=task.state.get("exception_recovery_round", 0) + 1)
    task.state.pop("retry_progress", None)
    task.state.pop("post_sync_task_id", None)
    task.status, task.finished_at, task.next_attempt_at, task.fence = "queued", None, None, None
    task.message = "按原时段处理异常：先核对及清理，再按原次数最多重建重试 3 次。"
    task.save(update_fields=["state", "status", "finished_at", "next_attempt_at", "fence", "message", "updated_at"])
    task.batch.finished_at = None
    task.batch.save(update_fields=["finished_at", "updated_at"])
    for notification in notifications:
        previous = {"status": notification.status, "message_id": notification.message_id,
            "snapshot": notification.snapshot}
        notification.snapshot = {**notification.snapshot, "phase": "recovery_pending",
            "recovery_revision": notification.snapshot.get("recovery_revision", 0) + 1,
            "recovery_started_at": timezone.now().isoformat(),
            "previous_receipt": previous}
        notification.status, notification.message, notification.message_id = "pending", "", ""
        notification.save(update_fields=["snapshot", "status", "message", "message_id", "updated_at"])
    return task


def reconcile_failed(task_id, *, adapter=None):
    """Read-only follow-up; never reopen execution or replay an uncertain write."""
    with transaction.atomic():
        task = StoreTask.objects.select_for_update().select_related("store").get(pk=task_id)
        if task.status != "failed" or not task.state.get("recovery_pending") or task.state.get("migration_hold"):
            raise ValidationError("该任务没有待核对的失败保护。")
        if task.lease_until and task.lease_until > timezone.now():
            raise ValidationError("原任务仍在核对中。")
        if not StoreLock.objects.filter(task=task, store_id=task.store_id, tenant_id=task.tenant_id).exists():
            raise ValidationError("店铺保护不一致，未执行核对。")
        task.fence, task.lease_until = uuid.uuid4(), timezone.now() + timedelta(minutes=3)
        task.save(update_fields=["fence", "lease_until", "updated_at"])
    adapter = adapter or ShopeeAdapter(task.store)
    def guard():
        if not StoreTask.objects.filter(pk=task.id, fence=task.fence, lease_until__gt=timezone.now()).exists():
            raise LeaseLost()
    if isinstance(adapter, ShopeeAdapter):
        adapter.guard = guard
    evidence = []
    try:
        for intent in task.intents.filter(reservation_key__isnull=False):
            guard()
            if intent.platform_id:
                detail = adapter.detail(intent.platform_id)
                absent = detail is None or detail.get("status") == 0
                ended = (bool(detail) and str(detail.get("timeslot_id")) == intent.slot_id
                    and detail.get("end_time") == intent.target.get("end_time") and detail["end_time"] <= time.time())
            else:
                matches = [r for r in adapter.activities(window=(intent.target["start_time"]-1, intent.target["end_time"]+1))
                    if str(r["timeslot_id"]) == intent.slot_id and r.get("status") != 0]
                ended = False
                absent = not matches and intent.target["end_time"] <= time.time()
            evidence.append((intent, absent, ended))
        with transaction.atomic():
            current = StoreTask.objects.select_for_update().get(pk=task.id)
            guard()
            resolved = bool(evidence) and all(absent or ended for _, absent, ended in evidence)
            for intent, absent, ended in evidence:
                if absent:
                    intent.absence_evidence = {"absent": True, "confirmed_at": timezone.now().isoformat(),
                        "platform_id": intent.platform_id, "read_only_followup": True}
                    intent.reservation_key = None
                intent.result["cleanup_status"] = "absent_readback" if absent else "retained_ended" if ended else "unconfirmed"
                intent.result["message"] = ("只读核对已确认活动不存在，未执行删除。" if absent else
                    "活动已结束，保留原活动与时段记录，未执行删除。" if ended else "写入或清理仍未确认，保护保留；未重复写入。")
                intent.save(update_fields=["absence_evidence", "reservation_key", "result", "updated_at"])
            current.state["recovery_pending"] = not resolved
            current.message = "执行失败；" + ("只读核对完成，已解除店铺互斥；详情保留实际清理证据。" if resolved else "只读核对仍未确认清理，店铺与时段保护保留。")
            if resolved:
                StoreLock.objects.filter(task=current).update(task=None)
            current.save(update_fields=["state", "message", "updated_at"])
    finally:
        StoreTask.objects.filter(pk=task.id, fence=task.fence).update(lease_until=None)
