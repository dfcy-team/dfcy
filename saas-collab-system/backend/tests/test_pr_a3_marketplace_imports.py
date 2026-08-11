from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
import threading
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import MarketplaceStoreMapping
from apps.marketplace_imports.adapters import PlatformResponseContractPending, get_real_response_adapter
from apps.marketplace_imports.models import (
    MarketplaceImportBatch,
    MarketplaceImportBatchAttempt,
    MarketplaceImportCursor,
    MarketplaceInventorySnapshot,
    MarketplaceOrder,
    import_service_write,
)
from apps.marketplace_imports.services import ImportRuleViolation
from apps.permissions.models import DataScope, Permission
from tests.test_pr_a2_store_mapping import client_for, grant, mapping_context


IMPORT_URL = "/api/internal/marketplace-imports/imports/"
BATCHES_URL = "/api/internal/marketplace-imports/batches/"
ORDERS_URL = "/api/internal/marketplace-imports/orders/"
INVENTORY_URL = "/api/internal/marketplace-imports/inventory/"
T1 = "2026-08-01T00:00:00Z"
T2 = "2026-08-02T00:00:00Z"
T3 = "2026-08-03T00:00:00Z"


def context(code, platform="shopee", permission="integrations.store.sync", scope=DataScope.ScopeType.ALL):
    tenant, user, _store, _config, authorization = mapping_context(code, platform=platform)
    from apps.integrations.store_mapping_service import create_store_mapping

    mapping = create_store_mapping(tenant=tenant, actor=user, store=authorization.store, authorization=authorization)
    if permission:
        grant(user, permission, scope_type=scope)
    return tenant, user, mapping


def order_record(order_id="order-1", *, status="shipped", updated_at=T1, amount="20.0000"):
    return {
        "platform_order_id": order_id,
        "status": status,
        "currency": "PHP",
        "total_amount": amount,
        "ordered_at": T1,
        "platform_updated_at": updated_at,
        "cancelled_at": T2 if status == "cancelled" else None,
        "line_items": [
            {
                "platform_line_id": f"line-{order_id}",
                "platform_variant_id": f"variant-{order_id}",
                "platform_sku": f"sku-{order_id}",
                "quantity": 2,
                "unit_price": "10.0000",
                "line_amount": "20.0000",
            }
        ],
        "refunds": [],
    }


def order_payload(mapping, *, key="orders-key-0001", mode="initial", before="", after="orders-c1", watermark=T1):
    return {
        "store_mapping_id": mapping.id,
        "resource_type": "orders",
        "import_mode": mode,
        "source_mode": "synthetic_contract",
        "idempotency_key": key,
        "cursor_before": before,
        "cursor_after": after,
        "watermark_after": watermark,
        "contract_version": "pr-a3-normalized-v1",
        "orders": [order_record()],
    }


def inventory_payload(mapping, *, key="inventory-key-0001", mode="initial", before="", after="inventory-c1", observed=T1):
    return {
        "store_mapping_id": mapping.id,
        "resource_type": "inventory",
        "import_mode": mode,
        "source_mode": "synthetic_contract",
        "idempotency_key": key,
        "cursor_before": before,
        "cursor_after": after,
        "watermark_after": observed,
        "contract_version": "pr-a3-normalized-v1",
        "inventory": [
            {
                "platform_variant_id": "variant-1",
                "platform_sku": "sku-1",
                "on_hand": 10,
                "reserved": 2,
                "available": 8,
                "incoming": 1,
                "observed_at": observed,
            }
        ],
    }


def processing_batch(tenant, user, mapping):
    attempt_id = uuid4()
    with import_service_write():
        batch = MarketplaceImportBatch.objects.create(
            tenant=tenant,
            store_mapping=mapping,
            platform=mapping.platform,
            resource_type="orders",
            import_mode="initial",
            source_mode="synthetic_contract",
            contract_version="pr-a3-normalized-v1",
            idempotency_key_hash=uuid4().hex * 2,
            payload_hash=uuid4().hex * 2,
            cursor_before="",
            cursor_after="orders-c1",
            received_count=1,
            attempt_version=1,
            active_attempt_id=attempt_id,
            created_by=user,
        )
    return batch, attempt_id


def attempt_kwargs(batch, actor, attempt_id=None, **overrides):
    values = {
        "batch": batch,
        "tenant": batch.tenant,
        "store_mapping": batch.store_mapping,
        "actor": actor,
        "attempt_id": attempt_id or batch.active_attempt_id or uuid4(),
        "attempt_version": batch.attempt_version,
        "action": MarketplaceImportBatchAttempt.Action.IMPORT,
        "previous_status": "",
        "new_status": MarketplaceImportBatch.Status.PROCESSING,
        "result": MarketplaceImportBatchAttempt.Result.STARTED,
        "controlled_error_code": "",
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_import_is_fail_closed_by_default():
    _tenant, user, mapping = context("a3-switch")
    response = client_for(user).post(IMPORT_URL, order_payload(mapping), format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "MARKETPLACE_IMPORT_REJECTED"
    assert not MarketplaceImportBatch.objects.exists()


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
@pytest.mark.parametrize("platform,resource", [("shopee", "orders"), ("tiktok", "inventory")])
def test_both_platforms_accept_only_normalized_synthetic_contract(platform, resource):
    tenant, user, mapping = context(f"a3-{platform}-{resource}", platform=platform)
    payload = order_payload(mapping) if resource == "orders" else inventory_payload(mapping)
    response = client_for(user).post(IMPORT_URL, payload, format="json")
    assert response.status_code == 201
    assert response.json()["data"]["batch"]["status"] == "completed"
    cursor = MarketplaceImportCursor.objects.get(tenant=tenant, resource_type=resource)
    assert cursor.version == 1
    assert cursor.cursor == payload["cursor_after"]
    batch = MarketplaceImportBatch.objects.get(tenant=tenant)
    assert batch.platform == platform
    if resource == "inventory":
        assert MarketplaceInventorySnapshot.objects.get(tenant=tenant).mapping_status == "unmapped"


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_idempotent_replay_returns_same_batch_without_advancing_cursor():
    tenant, user, mapping = context("a3-idempotent")
    payload = order_payload(mapping)
    first = client_for(user).post(IMPORT_URL, payload, format="json")
    second = client_for(user).post(IMPORT_URL, payload, format="json")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["duplicate"] is True
    assert first.json()["data"]["batch"]["id"] == second.json()["data"]["batch"]["id"]
    assert MarketplaceImportCursor.objects.get(tenant=tenant).version == 1
    assert MarketplaceOrder.objects.count() == 1


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_idempotency_key_cannot_be_reused_for_different_payload():
    _tenant, user, mapping = context("a3-idem-conflict")
    payload = order_payload(mapping)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 201
    changed = deepcopy(payload)
    changed["orders"][0]["total_amount"] = "21.0000"
    response = client_for(user).post(IMPORT_URL, changed, format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "MARKETPLACE_IMPORT_CONFLICT"


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_incremental_cursor_and_watermark_are_monotonic():
    tenant, user, mapping = context("a3-cursor")
    assert client_for(user).post(IMPORT_URL, order_payload(mapping), format="json").status_code == 201
    incremental = order_payload(
        mapping, key="orders-key-0002", mode="incremental", before="orders-c1", after="orders-c2", watermark=T2
    )
    incremental["orders"] = [order_record("order-2", updated_at=T2)]
    assert client_for(user).post(IMPORT_URL, incremental, format="json").status_code == 201
    cursor = MarketplaceImportCursor.objects.get(tenant=tenant)
    assert cursor.cursor == "orders-c2"
    assert cursor.version == 2

    stale = order_payload(
        mapping, key="orders-key-0003", mode="incremental", before="wrong", after="orders-c3", watermark=T1
    )
    response = client_for(user).post(IMPORT_URL, stale, format="json")
    assert response.status_code == 409
    cursor.refresh_from_db()
    assert cursor.cursor == "orders-c2"
    assert cursor.version == 2


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_out_of_order_order_event_is_skipped_and_terminal_transition_is_rejected():
    tenant, user, mapping = context("a3-events")
    initial = order_payload(mapping)
    initial["orders"] = [order_record(status="completed", updated_at=T2)]
    initial["watermark_after"] = T2
    assert client_for(user).post(IMPORT_URL, initial, format="json").status_code == 201

    older = order_payload(
        mapping, key="orders-key-older", mode="incremental", before="orders-c1", after="orders-c2", watermark=T2
    )
    older["orders"] = [order_record(status="shipped", updated_at=T1)]
    response = client_for(user).post(IMPORT_URL, older, format="json")
    assert response.status_code == 201
    assert response.json()["data"]["batch"]["skipped_count"] == 1

    terminal = order_payload(
        mapping, key="orders-key-term", mode="incremental", before="orders-c2", after="orders-c3", watermark=T3
    )
    terminal["orders"] = [order_record(status="shipped", updated_at=T3)]
    response = client_for(user).post(IMPORT_URL, terminal, format="json")
    assert response.status_code == 409
    assert MarketplaceImportCursor.objects.get(tenant=tenant).cursor == "orders-c2"
    assert MarketplaceOrder.objects.get(tenant=tenant).status == "completed"


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_same_timestamp_with_changed_content_rolls_back_entire_batch():
    tenant, user, mapping = context("a3-atomic")
    assert client_for(user).post(IMPORT_URL, order_payload(mapping), format="json").status_code == 201
    payload = order_payload(
        mapping, key="orders-key-atomic", mode="incremental", before="orders-c1", after="orders-c2", watermark=T2
    )
    conflict = order_record(updated_at=T1, amount="99.0000")
    payload["orders"] = [order_record("new-order", updated_at=T2), conflict]
    response = client_for(user).post(IMPORT_URL, payload, format="json")
    assert response.status_code == 409
    assert not MarketplaceOrder.objects.filter(platform_order_id="new-order").exists()
    assert MarketplaceImportCursor.objects.get(tenant=tenant).cursor == "orders-c1"
    failed = MarketplaceImportBatch.objects.get(idempotency_key_hash__isnull=False, status="failed")
    assert failed.controlled_error_code == "MARKETPLACE_IMPORT_CONFLICT"


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_refund_is_imported_and_terminal_refund_cannot_reopen():
    _tenant, user, mapping = context("a3-refund")
    payload = order_payload(mapping)
    payload["orders"][0]["refunds"] = [{
        "platform_refund_id": "refund-1", "status": "completed", "currency": "PHP",
        "amount": "5.0000", "reason_code": "CUSTOMER_RETURN", "platform_updated_at": T1,
    }]
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 201
    changed = order_payload(
        mapping, key="orders-key-refund", mode="incremental", before="orders-c1", after="orders-c2", watermark=T2
    )
    changed["orders"][0]["platform_updated_at"] = T2
    changed["orders"][0]["refunds"] = [{
        "platform_refund_id": "refund-1", "status": "approved", "currency": "PHP",
        "amount": "5.0000", "reason_code": "CUSTOMER_RETURN", "platform_updated_at": T2,
    }]
    assert client_for(user).post(IMPORT_URL, changed, format="json").status_code == 409


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
@pytest.mark.parametrize("refund_status", ["requested", "approved", "rejected", "completed", "cancelled"])
def test_all_normalized_refund_statuses_are_accepted(refund_status):
    _tenant, user, mapping = context(f"a3-refund-{refund_status}")
    payload = order_payload(mapping, key=f"refund-status-{refund_status}")
    payload["orders"][0]["refunds"] = [{
        "platform_refund_id": f"refund-{refund_status}", "status": refund_status, "currency": "PHP",
        "amount": "5.0000", "reason_code": "NORMALIZED_REASON", "platform_updated_at": T1,
    }]
    response = client_for(user).post(IMPORT_URL, payload, format="json")
    assert response.status_code == 201
    assert MarketplaceOrder.objects.get().refunds.get().status == refund_status


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_cancelled_order_cannot_be_restored_by_old_or_new_event():
    tenant, user, mapping = context("a3-cancelled")
    payload = order_payload(mapping)
    payload["orders"] = [order_record(status="cancelled", updated_at=T2)]
    payload["watermark_after"] = T2
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 201
    older = order_payload(
        mapping, key="cancelled-older", mode="incremental", before="orders-c1", after="orders-c2", watermark=T2
    )
    older["orders"] = [order_record(status="shipped", updated_at=T1)]
    assert client_for(user).post(IMPORT_URL, older, format="json").status_code == 201
    newer = order_payload(
        mapping, key="cancelled-newer", mode="incremental", before="orders-c2", after="orders-c3", watermark=T3
    )
    newer["orders"] = [order_record(status="shipped", updated_at=T3)]
    assert client_for(user).post(IMPORT_URL, newer, format="json").status_code == 409
    assert MarketplaceOrder.objects.get(tenant=tenant).status == "cancelled"


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_inventory_deduplication_and_timestamp_conflict():
    tenant, user, mapping = context("a3-inventory", platform="tiktok")
    payload = inventory_payload(mapping)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 201
    replay = inventory_payload(
        mapping, key="inventory-key-0002", mode="incremental", before="inventory-c1", after="inventory-c2", observed=T1
    )
    duplicate = client_for(user).post(IMPORT_URL, replay, format="json")
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["batch"]["skipped_count"] == 1
    conflict = inventory_payload(
        mapping, key="inventory-key-0003", mode="incremental", before="inventory-c2", after="inventory-c3", observed=T1
    )
    conflict["inventory"][0]["on_hand"] = 11
    assert client_for(user).post(IMPORT_URL, conflict, format="json").status_code == 409
    assert MarketplaceInventorySnapshot.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
@pytest.mark.parametrize("field,value", [("on_hand", -1), ("reserved", -1), ("available", -1), ("incoming", -1)])
def test_negative_inventory_is_rejected(field, value):
    _tenant, user, mapping = context(f"a3-negative-{field}", platform="tiktok")
    payload = inventory_payload(mapping)
    payload["inventory"][0][field] = value
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 422
    assert not MarketplaceInventorySnapshot.objects.exists()


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update({"tenant_id": 999}),
        lambda p: p.update({"platform": "shopee"}),
        lambda p: p.update({"access_token": "forbidden"}),
        lambda p: p["orders"][0].update({"authorization_code": "forbidden"}),
        lambda p: p["orders"][0].update({"total_amount": "-1.0000"}),
        lambda p: p.update({"source_mode": "live"}),
        lambda p: p.update({"contract_version": "guessed-v2"}),
    ],
)
def test_contract_rejects_identity_credentials_unknown_fields_and_invalid_values(mutation):
    _tenant, user, mapping = context(f"a3-bad-{abs(hash(str(mutation))) % 100000}")
    payload = order_payload(mapping)
    mutation(payload)
    response = client_for(user).post(IMPORT_URL, payload, format="json")
    assert response.status_code == 422
    assert not MarketplaceImportBatch.objects.exists()


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_exact_permission_and_data_scope_are_enforced():
    _tenant, user, mapping = context("a3-permission", permission=None)
    payload = order_payload(mapping)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 403
    grant(user, "integrations.store.view")
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 403
    grant(user, "integrations.store.sync", scope_type=None)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 403


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_view_sync_and_retry_permissions_do_not_replace_each_other():
    _tenant, user, mapping = context("a3-exact-actions")
    payload = order_payload(mapping)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 201
    assert client_for(user).get(BATCHES_URL).status_code == 403
    grant(user, "integrations.store.view")
    assert client_for(user).get(BATCHES_URL).status_code == 200
    assert client_for(user).get(ORDERS_URL).status_code == 200
    assert client_for(user).post(f"{BATCHES_URL}1/retry/", payload, format="json").status_code == 403


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
@pytest.mark.parametrize("scope_config", [{}, {"store_ids": ["bad"]}, {"unknown_key": [1]}])
def test_empty_invalid_and_unknown_store_scopes_are_rejected(scope_config):
    _tenant, user, mapping = context("a3-scope-" + str(abs(hash(str(scope_config))) % 10000), permission=None)
    grant(user, "integrations.store.sync", DataScope.ScopeType.CUSTOM, scope_config)
    response = client_for(user).post(IMPORT_URL, order_payload(mapping), format="json")
    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
@pytest.mark.parametrize("user_type", ["external", "rpa"])
def test_external_and_rpa_users_are_rejected(user_type):
    tenant, _internal, mapping = context(f"a3-{user_type}")
    from apps.accounts.models import CustomUser

    user = CustomUser.objects.create_user(
        username=f"a3-{user_type}-user", tenant=tenant, user_type=user_type
    )
    grant(user, "integrations.store.sync")
    assert client_for(user).post(IMPORT_URL, order_payload(mapping), format="json").status_code == 403


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_cross_tenant_mapping_is_hidden_as_not_found():
    _tenant_a, user_a, _mapping_a = context("a3-tenant-a")
    _tenant_b, _user_b, mapping_b = context("a3-tenant-b")
    response = client_for(user_a).post(IMPORT_URL, order_payload(mapping_b), format="json")
    assert response.status_code == 404


@pytest.mark.django_db
def test_unauthenticated_and_unsupported_methods_are_rejected():
    assert APIClient().post(IMPORT_URL, {}, format="json").status_code == 401
    _tenant, user, _mapping = context("a3-method", permission="integrations.store.view")
    assert client_for(user).delete(ORDERS_URL).status_code == 405
    assert client_for(user).patch(INVENTORY_URL, {}, format="json").status_code == 405


@pytest.mark.django_db
def test_models_block_direct_write_and_delete():
    tenant, user, mapping = context("a3-model-guard")
    order = MarketplaceOrder(
        tenant=tenant, store_mapping=mapping, platform_order_id="direct", status="shipped",
        currency="PHP", total_amount=1, ordered_at=T1, platform_updated_at=T1,
        line_items=[], fingerprint="0" * 64, last_batch_id=1,
    )
    with pytest.raises(ValidationError, match="import service"):
        order.save()
    with pytest.raises(ValidationError, match="cannot be bulk deleted"):
        MarketplaceImportBatch.objects.all().delete()


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_failed_batch_can_be_retried_with_same_payload(monkeypatch):
    _tenant, user, mapping = context("a3-retry")
    payload = order_payload(mapping)
    from apps.marketplace_imports import services

    original = services._upsert_order
    calls = {"count": 0}

    def transient_failure(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ImportRuleViolation("controlled transient failure")
        return original(**kwargs)

    monkeypatch.setattr(services, "_upsert_order", transient_failure)
    failed = client_for(user).post(IMPORT_URL, payload, format="json")
    assert failed.status_code == 422
    batch = MarketplaceImportBatch.objects.get(status="failed")
    grant(user, "integrations.store.retry")
    retried = client_for(user).post(f"{BATCHES_URL}{batch.id}/retry/", payload, format="json")
    assert retried.status_code == 200
    batch.refresh_from_db()
    assert batch.status == "completed"
    assert batch.attempt_version == 2
    assert batch.active_attempt_id is None
    attempts = list(batch.attempts.order_by("created_at", "id"))
    assert [attempt.action for attempt in attempts] == ["import", "import", "retry", "retry"]
    assert [attempt.attempt_version for attempt in attempts] == [1, 1, 2, 2]
    assert [attempt.result for attempt in attempts] == ["started", "failed", "started", "success"]
    assert attempts[1].controlled_error_code == "MARKETPLACE_IMPORT_REJECTED"
    assert all(attempt.actor_id == user.id for attempt in attempts)

    duplicate = client_for(user).post(f"{BATCHES_URL}{batch.id}/retry/", payload, format="json")
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["duplicate"] is True
    batch.refresh_from_db()
    assert batch.attempt_version == 2
    assert batch.attempts.count() == 4


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_import_attempt_audit_is_append_only():
    _tenant, user, mapping = context("a3-attempt-guard")
    assert client_for(user).post(IMPORT_URL, order_payload(mapping), format="json").status_code == 201
    attempt = MarketplaceImportBatchAttempt.objects.get(result="success")
    attempt.result = MarketplaceImportBatchAttempt.Result.FAILED
    with pytest.raises(ValidationError, match="append-only"):
        attempt.save()
    with pytest.raises(ValidationError, match="append-only"):
        MarketplaceImportBatchAttempt.objects.filter(pk=attempt.pk).update(result="failed")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceImportBatchAttempt.objects.filter(pk=attempt.pk).delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        attempt.delete()


@pytest.mark.django_db
def test_attempt_first_instance_save_requires_audit_service():
    tenant, user, mapping = context("a3-attempt-save-create")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt(**attempt_kwargs(batch, user)).save()
    assert not batch.attempts.exists()


@pytest.mark.django_db
def test_attempt_manager_create_requires_audit_service():
    tenant, user, mapping = context("a3-attempt-manager-create")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt.objects.create(**attempt_kwargs(batch, user))
    assert not batch.attempts.exists()


@pytest.mark.django_db
def test_attempt_get_or_create_creation_branch_requires_audit_service():
    tenant, user, mapping = context("a3-attempt-get-create")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt.objects.get_or_create(
            batch=batch,
            attempt_id=uuid4(),
            new_status=MarketplaceImportBatch.Status.PROCESSING,
            defaults=attempt_kwargs(batch, user),
        )
    assert not batch.attempts.exists()


@pytest.mark.django_db
def test_attempt_update_or_create_creation_branch_is_rejected():
    tenant, user, mapping = context("a3-attempt-update-create")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    with pytest.raises(ValidationError, match="append-only"):
        MarketplaceImportBatchAttempt.objects.update_or_create(
            batch=batch,
            attempt_id=uuid4(),
            new_status=MarketplaceImportBatch.Status.PROCESSING,
            defaults=attempt_kwargs(batch, user),
        )
    assert not batch.attempts.exists()


@pytest.mark.django_db
def test_attempt_bulk_create_is_rejected():
    tenant, user, mapping = context("a3-attempt-bulk-create")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    attempt = MarketplaceImportBatchAttempt(**attempt_kwargs(batch, user))
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt.objects.bulk_create([attempt])
    assert not batch.attempts.exists()


@pytest.mark.django_db
def test_attempt_base_manager_bulk_create_is_rejected():
    tenant, user, mapping = context("a3-attempt-base-manager-bulk-create")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    attempt = MarketplaceImportBatchAttempt(**attempt_kwargs(batch, user))
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt._base_manager.bulk_create([attempt])
    assert not batch.attempts.exists()


@pytest.mark.django_db
def test_controlled_audit_entry_creates_and_restores_creation_guard():
    tenant, user, mapping = context("a3-attempt-controlled")
    batch, attempt_id = processing_batch(tenant, user, mapping)
    from apps.marketplace_imports import services

    created = services._audit_attempt(
        batch=batch,
        actor=user,
        attempt_id=attempt_id,
        action=MarketplaceImportBatchAttempt.Action.IMPORT,
        previous_status="",
        new_status=MarketplaceImportBatch.Status.PROCESSING,
        result=MarketplaceImportBatchAttempt.Result.STARTED,
    )
    assert created.batch_id == batch.id
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt.objects.create(**attempt_kwargs(batch, user, attempt_id=uuid4()))


@pytest.mark.django_db
def test_existing_attempt_save_update_and_bulk_update_are_rejected():
    tenant, user, mapping = context("a3-attempt-update-guards")
    batch, attempt_id = processing_batch(tenant, user, mapping)
    from apps.marketplace_imports import services

    attempt = services._audit_attempt(
        batch=batch,
        actor=user,
        attempt_id=attempt_id,
        action=MarketplaceImportBatchAttempt.Action.IMPORT,
        previous_status="",
        new_status=MarketplaceImportBatch.Status.PROCESSING,
        result=MarketplaceImportBatchAttempt.Result.STARTED,
    )
    attempt.result = MarketplaceImportBatchAttempt.Result.FAILED
    with pytest.raises(ValidationError, match="append-only"):
        attempt.save()
    with pytest.raises(ValidationError, match="append-only"):
        MarketplaceImportBatchAttempt.objects.filter(pk=attempt.pk).update(result="failed")
    with pytest.raises(ValidationError, match="append-only"):
        MarketplaceImportBatchAttempt.objects.bulk_update([attempt], ["result"])
    with pytest.raises(ValidationError, match="append-only"):
        MarketplaceImportBatchAttempt.objects.update_or_create(
            pk=attempt.pk,
            defaults={"result": MarketplaceImportBatchAttempt.Result.FAILED},
        )


@pytest.mark.django_db
def test_attempt_instance_and_queryset_delete_are_rejected():
    tenant, user, mapping = context("a3-attempt-delete-guards")
    batch, attempt_id = processing_batch(tenant, user, mapping)
    from apps.marketplace_imports import services

    attempt = services._audit_attempt(
        batch=batch,
        actor=user,
        attempt_id=attempt_id,
        action=MarketplaceImportBatchAttempt.Action.IMPORT,
        previous_status="",
        new_status=MarketplaceImportBatch.Status.PROCESSING,
        result=MarketplaceImportBatchAttempt.Result.STARTED,
    )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        attempt.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceImportBatchAttempt.objects.filter(pk=attempt.pk).delete()


@pytest.mark.django_db
def test_controlled_audit_rejects_cross_tenant_actor_and_restores_guard():
    tenant, user, mapping = context("a3-attempt-actor-a")
    _other_tenant, other_user, _other_mapping = context("a3-attempt-actor-b")
    batch, attempt_id = processing_batch(tenant, user, mapping)
    from apps.marketplace_imports import services

    with pytest.raises(ValidationError) as exc:
        services._audit_attempt(
            batch=batch,
            actor=other_user,
            attempt_id=attempt_id,
            action=MarketplaceImportBatchAttempt.Action.IMPORT,
            previous_status="",
            new_status=MarketplaceImportBatch.Status.PROCESSING,
            result=MarketplaceImportBatchAttempt.Result.STARTED,
        )
    assert "actor" in exc.value.error_dict
    with pytest.raises(ValidationError, match="audit service"):
        MarketplaceImportBatchAttempt.objects.create(**attempt_kwargs(batch, user))


@pytest.mark.django_db
def test_attempt_validation_rejects_batch_tenant_mismatch():
    tenant, user, mapping = context("a3-attempt-tenant-a")
    other_tenant, other_user, _other_mapping = context("a3-attempt-tenant-b")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    attempt = MarketplaceImportBatchAttempt(
        **attempt_kwargs(batch, other_user, tenant=other_tenant)
    )
    with pytest.raises(ValidationError) as exc:
        attempt.full_clean()
    assert "batch" in exc.value.error_dict


@pytest.mark.django_db
def test_attempt_validation_rejects_batch_store_mapping_mismatch():
    tenant, user, mapping = context("a3-attempt-store-a")
    _other_tenant, _other_user, other_mapping = context("a3-attempt-store-b")
    batch, _attempt_id = processing_batch(tenant, user, mapping)
    attempt = MarketplaceImportBatchAttempt(
        **attempt_kwargs(batch, user, store_mapping=other_mapping)
    )
    with pytest.raises(ValidationError) as exc:
        attempt.full_clean()
    assert "store_mapping" in exc.value.error_dict


@pytest.mark.django_db
def test_controlled_audit_rejects_invalid_status_result_combination():
    tenant, user, mapping = context("a3-attempt-transition")
    batch, attempt_id = processing_batch(tenant, user, mapping)
    from apps.marketplace_imports import services

    with pytest.raises(ValidationError) as exc:
        services._audit_attempt(
            batch=batch,
            actor=user,
            attempt_id=attempt_id,
            action=MarketplaceImportBatchAttempt.Action.IMPORT,
            previous_status="",
            new_status=MarketplaceImportBatch.Status.PROCESSING,
            result=MarketplaceImportBatchAttempt.Result.SUCCESS,
        )
    assert "result" in exc.value.error_dict
    assert not batch.attempts.exists()


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_success_audit_failure_rolls_back_records_and_cursor(monkeypatch):
    tenant, user, mapping = context("a3-attempt-audit-rollback")
    from apps.marketplace_imports import services

    original_create = MarketplaceImportBatchAttempt.objects.create

    def fail_success_audit(**kwargs):
        if kwargs["result"] == MarketplaceImportBatchAttempt.Result.SUCCESS:
            raise RuntimeError("synthetic audit storage failure")
        return original_create(**kwargs)

    monkeypatch.setattr(MarketplaceImportBatchAttempt.objects, "create", fail_success_audit)
    response = client_for(user).post(IMPORT_URL, order_payload(mapping), format="json")
    assert response.status_code == 422
    batch = MarketplaceImportBatch.objects.get(tenant=tenant)
    assert batch.status == MarketplaceImportBatch.Status.FAILED
    assert batch.controlled_error_code == "MARKETPLACE_IMPORT_INTERNAL_FAILURE"
    assert list(batch.attempts.values_list("result", flat=True)) == ["started", "failed"]
    assert not MarketplaceOrder.objects.filter(tenant=tenant).exists()
    assert not MarketplaceImportCursor.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_stale_attempt_cannot_overwrite_completed_batch():
    tenant, user, mapping = context("a3-stale-attempt")
    payload = order_payload(mapping)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 201
    batch = MarketplaceImportBatch.objects.get(tenant=tenant)
    started = batch.attempts.get(result="started")
    from apps.marketplace_imports import services

    changed = services._fail_batch_attempt(
        batch_id=batch.id,
        actor=user,
        attempt_id=started.attempt_id,
        action=MarketplaceImportBatchAttempt.Action.IMPORT,
        controlled_error_code="STALE_ATTEMPT_MUST_NOT_WIN",
    )

    assert changed is False
    batch.refresh_from_db()
    cursor = MarketplaceImportCursor.objects.get(tenant=tenant, store_mapping=mapping, resource_type="orders")
    assert batch.status == "completed"
    assert batch.controlled_error_code == ""
    assert cursor.version == 1
    assert MarketplaceOrder.objects.filter(tenant=tenant, store_mapping=mapping).count() == 1
    assert batch.attempts.count() == 2


@pytest.mark.django_db(transaction=True)
@override_settings(PR_A3_SYNTHETIC_IMPORT_ENABLED=True)
def test_concurrent_failed_batch_retry_allows_at_most_one_mysql_commit(monkeypatch):
    if connection.vendor != "mysql":
        pytest.skip("MySQL failed-batch row-lock verification runs in Local Sandbox.")
    for code, name, action in (
        ("integrations.store.sync", "Synchronize marketplace stores", "store.sync"),
        ("integrations.store.retry", "Retry marketplace store operations", "store.retry"),
    ):
        Permission.objects.get_or_create(
            code=code,
            defaults={"name": name, "module": "integrations", "action": action},
        )
    tenant, user, mapping = context("a3-retry-mysql")
    payload = order_payload(mapping)
    from apps.marketplace_imports import services

    original = services._upsert_order
    calls = {"count": 0}

    def transient_failure(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ImportRuleViolation("controlled transient failure")
        return original(**kwargs)

    monkeypatch.setattr(services, "_upsert_order", transient_failure)
    assert client_for(user).post(IMPORT_URL, payload, format="json").status_code == 422
    batch = MarketplaceImportBatch.objects.get(status="failed")
    grant(user, "integrations.store.retry")
    start = threading.Event()

    def retry():
        close_old_connections()
        start.wait(timeout=5)
        try:
            actor = CustomUser.objects.get(pk=user.pk)
            response = client_for(actor).post(f"{BATCHES_URL}{batch.id}/retry/", payload, format="json")
            data = response.json().get("data") or {}
            duplicate = data.get("duplicate")
            return response.status_code, duplicate
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(retry) for _ in range(2)]
        start.set()
        results = [future.result(timeout=20) for future in futures]

    assert sum(status == 200 and duplicate is False for status, duplicate in results) == 1
    assert all(status in {200, 409} for status, _duplicate in results)
    batch.refresh_from_db()
    cursor = MarketplaceImportCursor.objects.get(
        tenant=tenant,
        store_mapping=mapping,
        resource_type="orders",
    )
    assert batch.status == "completed"
    assert batch.active_attempt_id is None
    assert batch.attempt_version == 2
    assert cursor.version == 1
    assert cursor.cursor == payload["cursor_after"]
    assert MarketplaceOrder.objects.filter(tenant=tenant, store_mapping=mapping).count() == 1
    assert batch.attempts.filter(action="retry", result="started").count() == 1
    assert batch.attempts.filter(action="retry", result="success").count() == 1


def test_real_response_adapter_is_explicitly_pending_and_has_no_fallback():
    for platform in ("shopee", "tiktok", "unknown"):
        with pytest.raises(PlatformResponseContractPending) as exc:
            get_real_response_adapter(platform)
        assert exc.value.error_code == "PLATFORM_RESPONSE_CONTRACT_PENDING"


def test_import_module_has_no_network_scheduler_webhook_or_platform_write_path():
    from apps.marketplace_imports import adapters, services, views

    source = "\n".join(inspect.getsource(module) for module in (adapters, services, views)).lower()
    for forbidden in ("import requests", "import httpx", "celery", "webhook", "platform write"):
        assert forbidden not in source
