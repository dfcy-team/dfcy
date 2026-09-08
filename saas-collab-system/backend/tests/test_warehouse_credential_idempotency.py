"""Retries cover the credential mutation as well as the warehouse binding."""

from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.integrations import warehouse_credential_service
from apps.integrations.models import IntegrationAuditLog, SyncJob, WarehouseAuthorization
from tests.test_warehouse_api_binding_closure import _fixture

pytestmark = pytest.mark.django_db


def setup_saved_binding(monkeypatch):
    actor, warehouse, config, _ = _fixture()
    custody = Mock()
    custody.store_secrets.side_effect = [
        {"credential_id": "synthetic-original"},
        {"credential_id": "synthetic-edited"},
    ]
    monkeypatch.setattr(warehouse_credential_service, "get_custody_backend", lambda: custody)
    client = APIClient()
    client.force_authenticate(actor)
    payload = {
        "warehouse_id": warehouse.pk, "integration_config_id": config.pk,
        "email": "demo@example.test", "token": "synthetic-bootstrap",
        "idempotency_key": "same-save-operation",
    }
    first = client.post("/api/internal/integrations/warehouse-authorizations/", payload, format="json")
    assert first.status_code == 201, first.data
    record = WarehouseAuthorization.objects.get()
    return client, payload, record, custody


def mark_oauth_complete(record):
    record.bootstrap_consumed_at = timezone.now()
    record.token_id = "synthetic-completed-oauth"
    record.oauth_user_id = "123"
    record.validation_status = "verified"
    record.last_verified_at = timezone.now()
    record.save()
    return (record.bootstrap_consumed_at, record.last_verified_at)


def test_replayed_binding_preserves_completed_oauth_and_enabled_job(monkeypatch):
    client, payload, record, custody = setup_saved_binding(monkeypatch)
    consumed_at, verified_at = mark_oauth_complete(record)
    job = SyncJob.objects.create(tenant_id=record.tenant_id, integration_config=record.integration_config,
        warehouse_authorization=record, resource_type="inventory_snapshot", is_enabled=True)
    audit_count = IntegrationAuditLog.objects.count()
    replay = client.post("/api/internal/integrations/warehouse-authorizations/", payload, format="json")
    assert replay.status_code == 200, replay.data
    assert replay.data["data"]["idempotent"] is True
    assert replay.data["data"]["operation"] == "replay"
    record.refresh_from_db()
    job.refresh_from_db()
    assert record.token_id == "synthetic-completed-oauth"
    assert record.bootstrap_consumed_at == consumed_at
    assert record.last_verified_at == verified_at
    assert record.validation_status == "verified"
    assert job.is_enabled
    assert custody.store_secrets.call_count == 1
    assert IntegrationAuditLog.objects.count() == audit_count


@pytest.mark.parametrize("changed", [
    {"email": "changed@example.test"},
    {"token": "synthetic-different-token"},
    {"token": ""},
    {"external_warehouse_code": "DIFFERENT-WAREHOUSE"},
])
def test_same_key_rejects_changed_payload_without_mutation(monkeypatch, changed):
    client, payload, record, custody = setup_saved_binding(monkeypatch)
    consumed_at, _ = mark_oauth_complete(record)
    response = client.post("/api/internal/integrations/warehouse-authorizations/", {**payload, **changed}, format="json")
    assert response.status_code == 409, response.data
    record.refresh_from_db()
    assert record.token_id == "synthetic-completed-oauth"
    assert record.bootstrap_consumed_at == consumed_at
    assert custody.store_secrets.call_count == 1


@pytest.mark.parametrize("use_rebind", [False, True])
def test_new_key_can_edit_same_binding_and_edit_retry_is_inert(monkeypatch, use_rebind):
    client, payload, record, custody = setup_saved_binding(monkeypatch)
    mark_oauth_complete(record)
    edited = {**payload, "email": "changed@example.test", "token": "synthetic-replacement", "idempotency_key": "new-save-operation"}
    endpoint = f"/api/internal/integrations/warehouse-authorizations/{record.pk}/rebind/" if use_rebind else "/api/internal/integrations/warehouse-authorizations/"
    response = client.post(endpoint, edited, format="json")
    assert response.status_code == 200, response.data
    assert response.data["data"]["operation"] == "already_bound"
    record.refresh_from_db()
    assert record.email == "changed@example.test"
    assert record.bootstrap_credential_id == "synthetic-edited"
    assert not record.token_id
    assert record.bootstrap_consumed_at is None
    consumed_at, _ = mark_oauth_complete(record)
    retry = client.post(endpoint, edited, format="json")
    assert retry.status_code == 200, retry.data
    assert retry.data["data"]["operation"] == "replay"
    record.refresh_from_db()
    assert record.token_id == "synthetic-completed-oauth"
    assert record.bootstrap_consumed_at == consumed_at
    assert custody.store_secrets.call_count == 2
    audit = str(list(IntegrationAuditLog.objects.values_list("masked_detail", flat=True)))
    assert "synthetic-bootstrap" not in audit
    assert "synthetic-replacement" not in audit
    assert "changed@example.test" not in audit


def test_same_binding_edit_without_key_remains_supported(monkeypatch):
    client, payload, record, custody = setup_saved_binding(monkeypatch)
    payload.pop("idempotency_key")
    payload["token"] = "synthetic-explicit-replacement"
    response = client.post("/api/internal/integrations/warehouse-authorizations/", payload, format="json")
    assert response.status_code == 200, response.data
    record.refresh_from_db()
    assert record.bootstrap_credential_id == "synthetic-edited"
    assert custody.store_secrets.call_count == 2
