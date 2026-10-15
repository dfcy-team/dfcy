"""Behavioral tests for the isolated supply notification workflow."""
from datetime import timedelta
from hashlib import sha256
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.supply_chain import notification_config as cfg, notifications as notify, services
from apps.supply_chain.models import (
    NotificationAttempt, NotificationDownload, NotificationEvidence,
    NotificationOutbox, NotificationPart, NotificationReceipt,
    NotificationThrottle, NotificationChannel, SupplierGroupBinding,
    domain_write,
)
from apps.supply_chain.worktool import RateLimited
from tests.test_supply_chain_v2_foundation import (
    confirmed_order, internal_user, po_payload, world,
)

BASE = "/api/internal/supply-chain/v2"


class MemoryCustody:
    def __init__(self):
        self.secrets = {}
        self.calls = []

    def store_secrets(self, **values):
        self.calls.append(("store", values.copy()))
        credential_id = f"ref-{len(self.calls)}"
        self.secrets[credential_id] = values["secret"]
        return {"credential_id": credential_id, "token_id": f"token-{len(self.calls)}",
                "reference_version": values["reference_version"]}

    def rotate_secrets(self, previous_credential_id, previous_token_id, **values):
        self.calls.append(("rotate", values.copy(), previous_credential_id, previous_token_id))
        credential_id = f"ref-{len(self.calls)}"
        self.secrets[credential_id] = values["secret"]
        return {"credential_id": credential_id, "token_id": f"token-{len(self.calls)}",
                "reference_version": values["reference_version"]}

    def retrieve_secret(self, credential_id):
        return self.secrets[credential_id]


class FakeWorkTool:
    def __init__(self, *, message_id="msg-1", online=True, result=None):
        self.message_id, self.is_online, self.result_value = message_id, online, result
        self.sent = []
        self.result_calls = []

    def online(self, channel):
        return self.is_online

    def send(self, channel, target, *, text=None, file_url=None, object_name=None):
        self.sent.append((target, text, file_url, object_name))
        return self.message_id

    def result(self, channel, message_id):
        self.result_calls.append(message_id)
        return self.result_value


def _channel(actor, supplier, custody, *, title="SupplierA", enabled=True):
    with patch("apps.supply_chain.notification_config.get_custody_backend", return_value=custody):
        channel = cfg.save_channel(actor, None, {
            "name": "supplier-notices", "sender_name": "Buyer", "device_name": "Work PC",
        }, "channel-create")
        channel = cfg.credentials(actor, channel.pk, {
            "expected_version": channel.version, "robot_id": "fake-robot-secret", "reason": "test setup",
        }, "credential-save")
        today = services.business_date()
        channel = cfg.qualify_channel(actor, channel.pk, {
            "expected_version": channel.version, "first_day": today - timedelta(days=1),
            "second_day": today, "first_day_count": 6, "second_day_count": 6,
            "evidence": "fake acceptance evidence", "contains_external_member": True,
            "documents_opened": True, "supplier_saved": True,
            "automatic_without_confirmation": True,
        }, "qualification")
        channel = cfg.save_channel(actor, channel.pk, {
            "expected_version": channel.version, "name": channel.name,
            "sender_name": channel.sender_name, "device_name": channel.device_name,
            "enabled": enabled,
        }, "channel-enable")
    binding = cfg.save_binding(actor, supplier.pk, {
        "expected_version": 0, "channel_id": channel.pk, "group_name": "Supplier A Group",
        "target_title": title, "member_count": 8, "group_note": "Supplier group",
        "contains_external_member": True, "sender_member_confirmed": True,
        "unique_target_confirmed": True, "evidence": "membership checked", "enabled": True,
    }, "binding-save")
    return channel, binding


def _ready(world, custody, *, title="SupplierA", key="notify"):
    actor = internal_user(world, f"notify-{key}", codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify"))
    channel, binding = _channel(actor, world["supplier"], custody, title=title)
    order = confirmed_order(world, actor, key=key, payload=po_payload(
        world, number=f"PO-{key}", lines=[{"sku_id": world["sku"].pk, "quantity": 10, "unit_price": "2.5"}],
    ))
    outbox = NotificationOutbox.objects.get(order=order)
    return actor, channel, binding, order, outbox


def _attempt(world, actor, channel, part, outbox, *, message_id, outcome="accepted", number=1):
    with domain_write():
        return NotificationAttempt.objects.create(tenant=world["tenant"], created_by=actor, part=part,
            channel=channel, number=number, outcome=outcome, provider_message_id=message_id,
            target_snapshot=outbox.target_snapshot)


@pytest.fixture
def custody():
    return MemoryCustody()


def test_confirmation_captures_target_and_prepare_freezes_snapshot_files_and_link(world, custody):
    actor, channel, binding = internal_user(world, "snapshot", codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify")), None, None
    channel, binding = _channel(actor, world["supplier"], custody)
    order = confirmed_order(world, actor, key="snapshot", payload=po_payload(
        world, number="PO-SNAPSHOT", lines=[{"sku_id": world["sku"].pk, "quantity": 7, "unit_price": "3.25"}],
    ))
    outbox = NotificationOutbox.objects.get(order=order)
    assert outbox.binding_id == binding.pk
    assert outbox.target_snapshot["target_title"] == "SupplierA"
    prepared = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "prepare-snapshot")
    parts = {part.kind: part for part in prepared.parts.all()}
    assert set(parts) == {"summary", "excel", "pdf", "link"}
    assert prepared.total_quantity == 7
    assert str(prepared.total_amount) == "22.7500"
    assert "PO-SNAPSHOT" in parts["summary"].text
    assert "总数量：7" in parts["summary"].text
    assert "总金额：22.7500" in parts["summary"].text
    assert b"PK" in bytes(parts["excel"].body)[:4]
    assert bytes(parts["pdf"].body).startswith(b"%PDF")
    assert "/supplier/orders/" in parts["link"].text
    assert all(part.sha256 == sha256(bytes(part.body) if part.body else part.text.encode()).hexdigest() for part in parts.values())


def test_preview_download_is_private_and_detects_tampered_bytes(world, custody):
    actor, _, _, _, outbox = _ready(world, custody, key="preview")
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "preview-prepare")
    part = outbox.parts.get(kind="pdf")
    client = APIClient(); client.force_authenticate(actor)
    path = f"{BASE}/notifications/{outbox.pk}/parts/{part.pk}/download/"
    response = client.get(path)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"%PDF" in b"".join(response.streaming_content)[:8]
    with domain_write():
        part.body = b"tampered"; part.save(update_fields=["body"])
    assert client.get(path).status_code == 404


def test_notify_permission_is_separate_from_view_and_manage(world, custody):
    actor = internal_user(world, "without-notify")
    client = APIClient(); client.force_authenticate(actor)
    response = client.post(f"{BASE}/notification-channels/", {
        "name": "x", "sender_name": "Buyer", "device_name": "PC",
    }, format="json")
    assert response.status_code == 403
    assert not NotificationChannel.objects.filter(tenant=world["tenant"]).exists()


def test_notify_scope_cannot_manage_supplier_outside_custom_scope(world, custody):
    actor = internal_user(world, "custom-notify", scope="custom", config={"supplier_ids": [world["supplier"].pk]},
                          codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify"))
    channel, _ = _channel(actor, world["supplier"], custody)
    with pytest.raises(Exception):
        cfg.save_binding(actor, world["supplier_b"].pk, {
            "expected_version": 0, "channel_id": channel.pk, "group_name": "Other Group",
            "target_title": "SupplierB", "member_count": 3, "group_note": "",
            "contains_external_member": True, "sender_member_confirmed": True,
            "unique_target_confirmed": True, "evidence": "checked", "enabled": True,
        }, "outside-scope")


@pytest.mark.parametrize("revoked", ["creator_manage", "enabled_by_notify"])
def test_guard_checks_source_creator_manage_and_channel_enabler_notify_separately(world, custody, revoked):
    actor, channel, _, _, outbox = _ready(world, custody, key="scope-" + revoked)
    if revoked == "creator_manage":
        source_actor = internal_user(world, "no-source-manage", codes=("supply.v2.view", "supply.v2.notify"))
        with domain_write():
            outbox.created_by = source_actor
            outbox.save()
    else:
        enable_actor = internal_user(world, "no-enable-notify", codes=("supply.v2.view", "supply.v2.manage"))
        with domain_write():
            channel.enabled_by = enable_actor
            channel.save()
    assert notify.guard(outbox) == "permission_revoked"


def test_credentials_are_write_only_and_rotation_resets_qualification(world, custody):
    actor = internal_user(world, "credentials", codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify"))
    client = APIClient(); client.force_authenticate(actor)
    created = client.post(f"{BASE}/notification-channels/", {
        "name": "secret-channel", "sender_name": "Buyer", "device_name": "PC",
    }, format="json", HTTP_IDEMPOTENCY_KEY="secret-channel").json()["data"]
    with patch("apps.supply_chain.notification_config.get_custody_backend", return_value=custody):
        response = client.post(f"{BASE}/notification-channels/{created['id']}/credentials/", {
            "expected_version": created["version"], "robot_id": "FAKE-ONLY-SECRET", "reason": "test rotation",
        }, format="json", HTTP_IDEMPOTENCY_KEY="secret-credential")
    assert response.status_code == 200
    body = str(response.json())
    assert "FAKE-ONLY-SECRET" not in body
    channel = NotificationChannel.objects.get(pk=created["id"])
    assert "FAKE-ONLY-SECRET" not in str(channel.__dict__)
    assert "FAKE-ONLY-SECRET" not in str(list(services.BusinessEvent.objects.values("payload")))
    version = channel.version
    with patch("apps.supply_chain.notification_config.get_custody_backend", return_value=custody):
        rotate = client.post(f"{BASE}/notification-channels/{channel.pk}/credentials/", {
            "expected_version": version, "robot_id": "ROTATED-FAKE-SECRET", "reason": "rotate test",
        }, format="json", HTTP_IDEMPOTENCY_KEY="rotate-credential")
    assert rotate.status_code == 200
    channel.refresh_from_db()
    assert channel.credential_version == 2
    assert channel.enabled is False and channel.enabled_by_id is None
    assert not cfg.qualified(channel)
    assert len(custody.calls) == 2 and custody.calls[1][0] == "rotate"
    assert "ROTATED-FAKE-SECRET" not in str(list(services.BusinessEvent.objects.values("payload")))


@pytest.mark.parametrize("changed", [
    {"first_day_count": 5}, {"second_day_count": 5}, {"contains_external_member": False},
    {"documents_opened": False}, {"supplier_saved": False},
    {"automatic_without_confirmation": False}, {"evidence": ""},
])
def test_channel_qualification_rejects_incomplete_acceptance(world, custody, changed):
    actor = internal_user(world, "qualify-" + str(len(changed)), codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify"))
    channel = cfg.save_channel(actor, None, {"name": "q", "sender_name": "Buyer", "device_name": "PC"}, "q-create")
    today = services.business_date()
    payload = {"expected_version": channel.version, "first_day": today - timedelta(days=1), "second_day": today,
               "first_day_count": 6, "second_day_count": 6, "evidence": "evidence",
               "contains_external_member": True, "documents_opened": True, "supplier_saved": True,
               "automatic_without_confirmation": True}
    payload.update(changed)
    with patch("apps.supply_chain.notification_config.get_custody_backend", return_value=custody):
        channel = cfg.credentials(actor, channel.pk, {"expected_version": channel.version, "robot_id": "fake", "reason": "test"}, "q-cred")
    payload["expected_version"] = channel.version
    with pytest.raises(Exception):
        cfg.qualify_channel(actor, channel.pk, payload, "q-acceptance")


def test_qualification_requires_ordered_distinct_days(world, custody):
    actor = internal_user(world, "qualify-days", codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify"))
    with patch("apps.supply_chain.notification_config.get_custody_backend", return_value=custody):
        channel = cfg.save_channel(actor, None, {"name": "days", "sender_name": "Buyer", "device_name": "PC"}, "days-create")
        channel = cfg.credentials(actor, channel.pk, {"expected_version": channel.version, "robot_id": "fake", "reason": "test"}, "days-cred")
    today = services.business_date()
    with pytest.raises(Exception):
        cfg.qualify_channel(actor, channel.pk, {
            "expected_version": channel.version, "first_day": today, "second_day": today,
            "first_day_count": 6, "second_day_count": 6, "evidence": "evidence",
            "contains_external_member": True, "documents_opened": True, "supplier_saved": True,
            "automatic_without_confirmation": True,
        }, "same-day")


def test_binding_requires_manual_verification_and_target_format(world, custody):
    actor = internal_user(world, "binding", codes=("supply.v2.view", "supply.v2.manage", "supply.v2.notify"))
    channel = cfg.save_channel(actor, None, {"name": "bind", "sender_name": "Buyer", "device_name": "PC"}, "b-create")
    for title, verified in (("SupplierA", False), ("Supplier-A", True)):
        with pytest.raises(Exception):
            cfg.save_binding(actor, world["supplier"].pk, {
                "expected_version": 0, "channel_id": channel.pk, "group_name": "Supplier Group",
                "target_title": title, "member_count": 4, "group_note": "",
                "contains_external_member": verified, "sender_member_confirmed": verified,
                "unique_target_confirmed": verified, "evidence": "checked" if verified else "",
                "enabled": True,
            }, f"bad-binding-{title}-{verified}")
    binding = cfg.save_binding(actor, world["supplier"].pk, {
        "expected_version": 0, "channel_id": channel.pk, "group_name": "Supplier Group",
        "target_title": "SupplierA", "member_count": 4, "group_note": "",
        "contains_external_member": True, "sender_member_confirmed": True,
        "unique_target_confirmed": True, "evidence": "checked", "enabled": True,
    }, "good-binding")
    assert cfg.binding_verified(binding)


def test_prepare_blocks_when_global_delivery_switch_is_off(world, custody, settings):
    actor, _, _, _, outbox = _ready(world, custody, key="disabled")
    settings.SUPPLY_NOTIFICATION_DELIVERY_ENABLED = False
    prepared = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "disabled-prepare")
    assert prepared.status == "blocked" and prepared.blocked_reason == "live_delivery_disabled"
    assert prepared.parts.count() == 4
    assert notify.dispatch_one(prepared.pk, adapter=FakeWorkTool()) == "blocked"


def test_dispatch_acceptance_and_callback_duplicate_are_idempotent(world, custody, settings):
    actor, channel, _, _, outbox = _ready(world, custody, key="callback")
    settings.SUPPLY_NOTIFICATION_DELIVERY_ENABLED = True
    prepared = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "callback-prepare")
    with domain_write():
        channel.connectivity, channel.last_checked_at = "online", timezone.now(); channel.save()
    adapter = FakeWorkTool(message_id="callback-msg")
    assert notify.dispatch_one(prepared.pk, adapter=adapter) == "accepted"
    attempt = NotificationAttempt.objects.get(provider_message_id="callback-msg")
    assert attempt.outcome == "accepted"
    callback = {"messageId": "callback-msg", "errorCode": 0, "type": 203,
                "successList": ["SupplierA"], "failList": []}
    notify.record_result(channel, callback)
    notify.record_result(channel, callback)
    attempt.refresh_from_db()
    assert attempt.outcome == "executed"
    assert NotificationReceipt.objects.filter(attempt=attempt).count() == 1
    assert attempt.part.status == "executed"


@pytest.mark.parametrize("result,expected", [
    ({"messageId": "cb", "errorCode": 0, "type": 203, "successList": ["WrongGroup"], "failList": []}, "unknown"),
    ({"messageId": "cb", "errorCode": 0, "type": 218, "successList": ["SupplierA"], "failList": []}, "unknown"),
    ({"messageId": "cb", "errorCode": 9, "type": 203, "successList": [], "failList": ["SupplierA"]}, "failed"),
])
def test_callback_requires_expected_type_and_exact_target(world, custody, result, expected):
    actor, channel, _, _, outbox = _ready(world, custody, key="cb-" + expected + str(result["type"]))
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "cb-prepare")
    part = outbox.parts.get(kind="summary")
    attempt = _attempt(world, actor, channel, part, outbox, message_id="cb")
    notify.record_result(channel, result)
    attempt.refresh_from_db(); part.refresh_from_db()
    assert attempt.outcome == expected
    assert part.status == expected


def test_not_delivered_observation_requires_stopped_execution_and_only_failed_can_retry(world, custody):
    actor, channel, _, _, outbox = _ready(world, custody, key="retry")
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "retry-prepare")
    part = outbox.parts.get(kind="summary")
    attempt = _attempt(world, actor, channel, part, outbox, message_id="retry-msg", outcome="unknown")
    with domain_write():
        part.status = "unknown"; part.save()
    with pytest.raises(Exception):
        notify.verify(actor, outbox.pk, part.pk, {"expected_version": part.version, "result": "not_delivered",
                       "evidence": "not in group", "execution_stopped": False}, "unsafe-verify")
    verified = notify.verify(actor, outbox.pk, part.pk, {"expected_version": part.version, "result": "not_delivered",
                       "evidence": "checked actual target; stopped", "execution_stopped": True}, "safe-verify")
    part.refresh_from_db()
    assert part.status == "failed" and part.evidence.count() == 1
    retried = notify.retry(actor, verified.pk, part.pk, {"expected_version": part.version, "reason": "verified stopped"}, "retry-failed")
    part.refresh_from_db()
    assert part.status == "pending" and part.attempts.count() == 1


def test_retry_rejects_unknown_without_human_evidence(world, custody):
    actor, channel, _, _, outbox = _ready(world, custody, key="unknown-retry")
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "ur-prepare")
    part = outbox.parts.get(kind="summary")
    with domain_write():
        part.status = "unknown"; part.save()
    with pytest.raises(Exception):
        notify.retry(actor, outbox.pk, part.pk, {"expected_version": part.version, "reason": "retry"}, "ur-retry")


def test_file_grant_stores_hash_expires_and_limits_downloads(world, custody):
    actor, channel, _, _, outbox = _ready(world, custody, key="grant")
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "grant-prepare")
    part = outbox.parts.get(kind="pdf")
    attempt = _attempt(world, actor, channel, part, outbox, message_id="grant-msg")
    url = notify._file_grant(attempt)
    token = url.rstrip("/").split("/")[-1]
    grant = NotificationDownload.objects.get(attempt=attempt)
    assert grant.token_hash == sha256(token.encode()).hexdigest()
    assert token not in grant.token_hash
    assert notify.download_material(attempt.pk, token)[1] == bytes(part.body)
    grant.refresh_from_db()
    with domain_write():
        grant.download_count = 10; grant.save()
    with pytest.raises(Exception):
        notify.download_material(attempt.pk, token)
    with domain_write():
        grant.download_count = 0; grant.expires_at = timezone.now() - timedelta(seconds=1); grant.save()
    with pytest.raises(Exception):
        notify.download_material(attempt.pk, token)


def test_worktool_throttle_is_global_and_rejects_request_before_window(world):
    throttle = NotificationThrottle.objects.create(provider="worktool", next_at=timezone.now() - timedelta(seconds=1))
    from apps.supply_chain.worktool import reserve_request
    reserve_request()
    throttle.refresh_from_db()
    assert throttle.next_at > timezone.now()
    with pytest.raises(RateLimited):
        reserve_request()


def test_dispatch_never_retries_unknown_attempt_and_reaper_marks_stale_as_unknown(world, custody, settings):
    actor, channel, _, _, outbox = _ready(world, custody, key="reap")
    settings.SUPPLY_NOTIFICATION_DELIVERY_ENABLED = True
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "reap-prepare")
    with domain_write():
        channel.connectivity, channel.last_checked_at = "online", timezone.now(); channel.save()
    adapter = FakeWorkTool(message_id="ambiguous")
    assert notify.dispatch_one(outbox.pk, adapter=adapter) == "accepted"
    attempt = NotificationAttempt.objects.get(provider_message_id="ambiguous")
    with domain_write():
        attempt.started_at = timezone.now() - timedelta(minutes=11); attempt.save()
    notify.reap_uncertain(outbox.pk)
    attempt.refresh_from_db()
    assert attempt.outcome == "unknown"
    sent_before = len(adapter.sent)
    assert notify.dispatch_one(outbox.pk, adapter=adapter) == "waiting_execution"
    assert adapter.result_calls == ["ambiguous"]
    assert len(adapter.sent) == sent_before


def test_reconcile_queries_provider_but_keeps_unresolved_instruction_stopped(world, custody):
    actor, channel, _, _, outbox = _ready(world, custody, key="reconcile")
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "rec-prepare")
    part = outbox.parts.get(kind="summary")
    attempt = _attempt(world, actor, channel, part, outbox, message_id="query-msg")
    with domain_write():
        part.status = "accepted"; part.save()
    adapter = FakeWorkTool(result=None)
    result = notify.reconcile(actor, outbox.pk, {"expected_version": outbox.version}, "reconcile", adapter=adapter)
    assert adapter.result_calls == ["query-msg"]
    part.refresh_from_db(); attempt.refresh_from_db()
    assert part.status == "accepted" and attempt.outcome == "accepted"


def test_callback_signature_is_required_and_duplicate_callback_is_safe(world, custody):
    actor, channel, _, _, outbox = _ready(world, custody, key="callback-api")
    outbox = notify.prepare(actor, outbox.pk, {"expected_version": outbox.version}, "cba-prepare")
    part = outbox.parts.get(kind="summary")
    attempt = _attempt(world, actor, channel, part, outbox, message_id="api-msg")
    callback_url = cfg.callback_link(channel)
    signature = callback_url.split("signature=")[-1]
    client = APIClient()
    body = {"messageId": "api-msg", "errorCode": 0, "type": 203, "successList": ["SupplierA"], "failList": []}
    endpoint = f"/api/supply-notifications/worktool/{channel.pk}/callback/"
    assert client.post(endpoint, body, format="json").status_code == 403
    assert client.post(endpoint + f"?signature={signature}", body, format="json").status_code == 200
    assert client.post(endpoint + f"?signature={signature}", body, format="json").status_code == 200
    assert NotificationReceipt.objects.filter(attempt=attempt).count() == 1
