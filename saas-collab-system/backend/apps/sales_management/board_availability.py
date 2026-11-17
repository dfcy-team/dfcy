"""Permission-keyed sales snapshots; expensive reads run only on a dedicated queue."""
import copy
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, time as clock_time, timezone as dt_timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import redis
from celery import current_app, shared_task
from django.conf import settings
from django.http import QueryDict
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.accounts.serializers import CurrentUserSerializer
from apps.integrations.models import PlatformIntegrationConfig
from apps.masterdata.exchange_rates import tenant_cny_rates
from apps.masterdata.models import StoreMaster, PlatformMaster, CountrySiteMaster, WarehouseMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes

logger = logging.getLogger(__name__)
PREFIX = "sales-board:v1:"
FRESH_SECONDS = 60
MAX_AGE_SECONDS = 600
LEASE_SECONDS = 120
QUEUE = "realtime_board"


class BoardTemporarilyUnavailable(APIException):
    status_code = 503
    default_detail = "大屏更新服务暂不可用，当前页面会保留上次结果。"
    default_code = "board_update_unavailable"


def store():
    return redis.Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5,
        retry_on_timeout=False, decode_responses=True,
    )


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def authority(request):
    user = request.user
    cache = getattr(request, "_permission_resolution_cache", {})
    if not user.is_active or user.user_type != "internal" or not check_user_permission(user, "sales_management.view", cache=cache):
        raise PermissionDenied()
    if not get_permission_data_scopes(user, "sales_management.view", cache=cache):
        raise PermissionDenied()
    # Resolve on every request: role/resource revocations and membership expiry
    # must never reuse an earlier authorization snapshot.
    signature = CurrentUserSerializer(user).get_authorization_version(user)
    identities = {}
    # Hash policy-relevant identities, not updated_at: routine sync/heartbeat
    # writes must not continuously invalidate an otherwise unchanged scope.
    identity_fields = (
        (StoreMaster, ("id", "platform", "country_code", "currency", "timezone", "status")),
        (PlatformMaster, ("id", "platform_type", "code", "status")),
        (CountrySiteMaster, ("id", "platform", "code", "site_code", "country_code", "status")),
        (WarehouseMaster, ("id", "country_code", "service_platform", "warehouse_type", "status", "legacy_codes")),
        (PlatformIntegrationConfig, ("id", "platform", "status", "config_version", "regions", "scopes", "deleted_at", "credential_status")),
    )
    for model, names in identity_fields:
        available = {field.name for field in model._meta.fields}
        fields = [name for name in names if name in available]
        identities[model._meta.label] = list(model.objects.filter(tenant_id=user.tenant_id).order_by("pk").values(*fields))
    return digest({"authorization": signature, "identities": identities})


def specification(request):
    from .realtime_board import _board_filters
    params, start, end = _board_filters(request)
    target = (params.get("display_currency") or "").strip().upper()
    if target and target not in tenant_cny_rates(request.user.tenant):
        raise ValidationError({"display_currency": "不支持该展示币种。"})
    if target:
        params["display_currency"] = target
    return {
        "user_id": request.user.pk, "tenant_id": request.user.tenant_id,
        "membership_id": getattr(request.user, "_active_membership_id", None),
        "params": dict(params.items()), "authority": authority(request),
    }


def snapshot_key(spec):
    return PREFIX + "snapshot:" + digest(spec)


def enqueue(client, spec, key):
    lease = key + ":refresh"
    token = uuid.uuid4().hex
    if not client.set(lease, token, nx=True, ex=LEASE_SECONDS):
        return False
    try:
        current_app.send_task(
            "sales.realtime_board.refresh", args=[spec, key, token], queue=QUEUE,
            expires=LEASE_SECONDS, retry=False, ignore_result=True,
        )
        return True
    except Exception:
        release(client, lease, token)
        logger.warning("Unable to enqueue board refresh", exc_info=True)
        raise BoardTemporarilyUnavailable()


def release(client, key, token):
    client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key, token)


def snapshot_payload(request):
    spec = specification(request)
    key = snapshot_key(spec)
    if request is not None:
        request._board_scope_version = spec["authority"]
    try:
        client = store()
        raw = client.get(key)
        entry = json.loads(raw) if raw else None
        now = time.time()
        age = max(0, now - entry["generated_at"]) if entry else None
        if entry and (age > MAX_AGE_SECONDS or (entry.get("valid_until") is not None and now >= entry["valid_until"])):
            entry = None
        # Registry is per user and filters, bounded by expiry; no credentials.
        registry_key = PREFIX + "active:" + digest({k: v for k, v in spec.items() if k != "authority"})
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)).isoformat()
        rolling = spec["params"].get("date_from") == spec["params"].get("date_to") == today
        client.set(registry_key, json.dumps({"spec": spec, "seen_at": now, "rolling_today": rolling}), ex=8 * 86400)
        if not entry or age >= FRESH_SECONDS:
            try:
                enqueue(client, spec, key)
            except BoardTemporarilyUnavailable:
                if not entry:
                    raise
        if not entry:
            return {"currency_groups": [], "availability": {
                "state": "warming", "generated_at": None, "age_seconds": None, "retry_after": 2,
                "scope_version": spec["authority"],
            }}
        payload = copy.deepcopy(entry["payload"])
        payload["availability"] = {
            "state": "fresh" if age < FRESH_SECONDS else "refreshing",
            "scope_version": spec["authority"],
            "generated_at": datetime.fromtimestamp(entry["generated_at"], dt_timezone.utc).isoformat(),
            "age_seconds": int(age), "retry_after": 60,
            "valid_until": datetime.fromtimestamp(entry["valid_until"], dt_timezone.utc).isoformat() if entry.get("valid_until") is not None else None,
        }
        return payload
    except (redis.RedisError, ValueError, KeyError, TypeError):
        logger.warning("Board snapshot store unavailable", exc_info=True)
        # Do not fall back to an expensive synchronous query during overload.
        raise BoardTemporarilyUnavailable()


def actor_request(spec):
    user = CustomUser.objects.get(pk=spec["user_id"], tenant_id=spec["tenant_id"], is_active=True)
    if spec.get("membership_id") is not None:
        from apps.permissions.models import OrgMembership
        from django.utils import timezone
        try:
            membership = OrgMembership.objects.select_related("department").get(
                pk=spec["membership_id"], user=user, tenant_id=user.tenant_id, status="active",
                department__status="active")
        except OrgMembership.DoesNotExist:
            raise PermissionDenied()
        if membership.valid_until and membership.valid_until <= timezone.now():
            raise PermissionDenied()
        user._active_membership_id = membership.pk
    params = QueryDict("", mutable=True)
    params.update(spec["params"])
    return SimpleNamespace(user=user, query_params=params, _permission_resolution_cache={})


@shared_task(name="sales.realtime_board.refresh", soft_time_limit=85, time_limit=100, ignore_result=True)
def refresh_board_snapshot(spec, key, token):
    client = store()
    try:
        if key != snapshot_key(spec) or client.get(key + ":refresh") != token:
            return
        request = actor_request(spec)
        if authority(request) != spec["authority"]:
            return
        from .realtime_board import realtime_board_payload
        payload = realtime_board_payload(request)
        # Re-read identity and grants after slow work, before publishing.
        if authority(actor_request(spec)) != spec["authority"]:
            return
        if client.get(key + ":refresh") != token:
            return
        valid_until = getattr(request, "_board_inventory_valid_until", None)
        client.set(key, json.dumps({"generated_at": time.time(), "payload": payload, "valid_until": valid_until.timestamp() if valid_until else None}, default=str), ex=MAX_AGE_SECONDS)
    finally:
        release(client, key + ":refresh", token)


def prewarm_recent(max_idle_seconds=300):
    """Dispatch previously requested scopes only; invoked by an operational timer."""
    client = store()
    scheduled = 0
    now = time.time()
    for key in client.scan_iter(match=PREFIX + "active:*", count=20):
        raw = client.get(key)
        if not raw:
            continue
        record = json.loads(raw)
        if now - record["seen_at"] > max_idle_seconds:
            continue
        try:
            if record.get("rolling_today"):
                from django.utils import timezone
                from zoneinfo import ZoneInfo
                today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)).isoformat()
                record["spec"]["params"].update(date_from=today, date_to=today)
            request = actor_request(record["spec"])
            spec = specification(request)
            snapshot = snapshot_key(spec)
            raw_entry = client.get(snapshot)
            entry = json.loads(raw_entry) if raw_entry else None
            if not entry or now - entry["generated_at"] >= FRESH_SECONDS:
                scheduled += int(bool(enqueue(client, spec, snapshot)))
        except (CustomUser.DoesNotExist, PermissionDenied, ValidationError):
            client.delete(key)
            continue
        if scheduled >= 20:
            break
    return scheduled


@shared_task(name="sales.realtime_board.prewarm", soft_time_limit=25, time_limit=30, ignore_result=True)
def prewarm_during_work_hours():
    """Refresh only recently accessed scopes during the Shanghai service window."""
    now = datetime.now(ZoneInfo("Asia/Shanghai")).time()
    if not settings.BOARD_PREWARM_ENABLED or not clock_time(8, 45) <= now < clock_time(19):
        return 0
    return prewarm_recent()
