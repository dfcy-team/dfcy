from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
from apps.commerce.models import SalesOrder
from apps.integrations.adapters import ProductionReadonlyAdapter
from apps.integrations.models import HistorySyncBatch, HistorySyncSegment, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster
from apps.tenants.models import Tenant
from tests.test_shopee_tiktok_finance_ingestion import _finance_scope
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import (
    TikTokReadonlyClient, _tiktok_explicit_empty_orders,
    _tiktok_trusted_terminal_orders_proof,
)


@pytest.mark.parametrize("token", [None, ""])
def test_explicit_empty_order_response_accepts_only_documented_zero_shape(token):
    payload = {"code": 0, "data": {"total_count": 0, "next_page_token": token}}

    assert _tiktok_explicit_empty_orders(payload, payload["data"])


@pytest.mark.parametrize("payload,data", [
    ({"data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": False, "data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": "0", "data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": 1, "data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": 0, "data": {"next_page_token": ""}}, {"next_page_token": ""}),
    ({"code": 0, "data": {"total_count": False, "next_page_token": ""}}, {"total_count": False, "next_page_token": ""}),
    ({"code": 0, "data": {"total_count": "0", "next_page_token": ""}}, {"total_count": "0", "next_page_token": ""}),
    ({"code": 0, "data": {"total_count": 0}}, {"total_count": 0}),
    ({"code": 0, "data": {"total_count": 0, "next_page_token": "next"}}, {"total_count": 0, "next_page_token": "next"}),
    ({"code": 0, "data": {"total_count": 0, "next_page_token": "", "orders": []}}, {"total_count": 0, "next_page_token": "", "orders": []}),
    ({"code": 0, "data": {"total_count": 0, "next_page_token": "", "orders": None}}, {"total_count": 0, "next_page_token": "", "orders": None}),
])
def test_other_order_response_shapes_are_not_explicit_empty(payload, data):
    assert not _tiktok_explicit_empty_orders(payload, data)


@pytest.mark.parametrize("token", [None, ""])
def test_fetch_orders_accepts_explicit_empty_page_without_detail_request(token):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    payload = {"code": 0, "data": {"total_count": 0, "next_page_token": token}}
    client._request = Mock(return_value=payload)

    result = client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created"})

    assert result["records"] == []
    assert result["next_cursor"] == ""
    assert result["raw_responses"] == [{"endpoint": client.ORDER_LIST_PATH, "payload": payload}]
    client._request.assert_called_once()


@pytest.mark.parametrize("data", [
    {"total_count": 0},
    {"total_count": False, "next_page_token": ""},
    {"total_count": 0, "next_page_token": "", "orders": None},
])
def test_fetch_orders_keeps_rejecting_malformed_empty_page(data):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    client._request = Mock(return_value={"code": 0, "data": data})

    with pytest.raises(ValidationError, match="missing data.orders") as exc:
        client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created"})
    assert client._request.call_count == (2 if "orders" not in data else 1)
    if "orders" not in data:
        assert "diagnostic(orders=absent" in str(exc.value)
        assert "input_cursor=False" in str(exc.value)


def test_fetch_orders_retries_missing_orders_once_and_preserves_both_responses():
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    malformed = {"code": 0, "data": {"total_count": 2, "next_page_token": "next"}}
    recovered = {"code": 0, "data": {"total_count": 0, "next_page_token": ""}}
    client._request = Mock(side_effect=[malformed, recovered])

    page = client.fetch_orders("provider-cursor", {
        "time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created",
    })

    assert page["records"] == [] and page["next_cursor"] == ""
    assert page["raw_responses"] == [
        {"endpoint": client.ORDER_LIST_PATH, "payload": malformed},
        {"endpoint": client.ORDER_LIST_PATH, "payload": recovered},
    ]
    assert client._request.call_count == 2
    assert client._request.call_args_list[0] == client._request.call_args_list[1]


def test_trusted_terminal_history_proof_accepts_exact_positive_match():
    payload = {"code": 0}
    data = {"total_count": 1450, "next_page_token": ""}
    callback = Mock(return_value=True)

    assert _tiktok_trusted_terminal_orders_proof(
        payload, data, cursor="provider-cursor", proof_callback=callback
    )
    callback.assert_called_once_with(1450)


@pytest.mark.parametrize("cursor,data,payload,callback", [
    ("provider-cursor", {"total_count": 1451, "next_page_token": ""}, {"code": 0}, Mock(return_value=False)),
    ("provider-cursor", {"total_count": 1450, "next_page_token": ""}, {"code": 0}, None),
    ("", {"total_count": 1450, "next_page_token": ""}, {"code": 0}, Mock(return_value=True)),
    ("provider-cursor", {"total_count": 1450, "next_page_token": "", "orders": None}, {"code": 0}, Mock(return_value=True)),
    ("provider-cursor", {"total_count": True, "next_page_token": ""}, {"code": 0}, Mock(return_value=True)),
    ("provider-cursor", {"total_count": 0, "next_page_token": ""}, {"code": 0}, Mock(return_value=True)),
    ("provider-cursor", {"total_count": 1450}, {"code": 0}, Mock(return_value=True)),
    ("provider-cursor", {"total_count": 1450, "next_page_token": "next"}, {"code": 0}, Mock(return_value=True)),
    ("provider-cursor", {"total_count": 1450, "next_page_token": ""}, {"code": False}, Mock(return_value=True)),
])
def test_trusted_terminal_history_proof_fails_closed(cursor, data, payload, callback):
    assert not _tiktok_trusted_terminal_orders_proof(
        payload, data, cursor=cursor, proof_callback=callback
    )


@pytest.mark.django_db
def test_tiktok_history_proof_uses_scoped_persisted_orders_including_final_second():
    tenant, store, config, authorization, job, _ = _finance_scope("tiktok")
    job.resource_type = SyncJob.ResourceType.SALES_ORDER
    job.save(update_fields=["resource_type"])
    platform = PlatformMaster.objects.get(tenant=tenant, code="tiktok")
    start = int(datetime(2026, 9, 15, tzinfo=UTC).timestamp())
    end = int(datetime(2026, 9, 21, 23, 59, 59, tzinfo=UTC).timestamp())
    scope = {"time_from": start, "time_to": end, "time_basis": "created", "page_size": 100}
    batch = HistorySyncBatch.objects.create(
        tenant=tenant, created_by=config.created_by, name="proof", idempotency_key="proof",
        request_hash="a" * 64, start_date=date(2026, 9, 15), end_date=date(2026, 9, 21),
    )
    segment = HistorySyncSegment.objects.create(batch=batch, sync_job=job, sequence=1, scope=scope)
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, history_segment=segment,
        run_id="proof-run", idempotency_key="proof-run", fetched_count=2, created_count=2)
    end_inclusive = datetime.fromtimestamp(end, UTC)
    for external_id, created in (("before", datetime.fromtimestamp(start, UTC)),
                                 ("last-second", end_inclusive)):
        SalesOrder.objects.create(
            tenant=tenant, platform=platform, store=store, authorization=config, source_run=run,
            external_order_id=external_id, region="PH", raw_status="COMPLETED",
            normalized_status="completed", status_mapping_version="1.0",
            created_at_utc=created, updated_at_utc=created, business_date=date(2026, 9, 21),
            currency="PHP", subtotal_amount=Decimal("1"), order_total_amount=Decimal("1"),
            payload_hash=hashlib.sha256(external_id.encode()).hexdigest(),
        )
    adapter = ProductionReadonlyAdapter(config)
    adapter.authorization, adapter.scope, adapter.source_run = authorization, dict(scope), run
    assert adapter._tiktok_history_terminal_orders_proof(job, 2)

    # Exercise the adapter-installed callback through the actual client path.
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = authorization
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    response = {"code": 0, "data": {"total_count": 2, "next_page_token": ""}}
    client._request = Mock(return_value=response)
    adapter.client = client
    page = adapter.fetch_page(job, "provider-cursor")
    assert page["records"] == [] and page["next_cursor"] == ""
    client._request.assert_called_once()

    # A row persisted by another segment cannot prove this segment complete.
    SalesOrder.objects.filter(external_order_id="last-second").update(source_run=SyncRun.objects.create(
        tenant=tenant, sync_job=job, run_id="other-run", idempotency_key="other-run",
    ))
    assert not adapter._tiktok_history_terminal_orders_proof(job, 2)

    SalesOrder.objects.filter(external_order_id="last-second").update(source_run=run)
    adapter.scope["time_to"] -= 1
    assert not adapter._tiktok_history_terminal_orders_proof(job, 2)

    adapter.scope = dict(scope)
    too_long = {**scope, "time_to": start + 30 * 86400}
    segment.scope = too_long
    segment.save(update_fields=["scope"])
    adapter.scope = dict(too_long)
    assert not adapter._tiktok_history_terminal_orders_proof(job, 2)

    segment.scope = scope
    segment.save(update_fields=["scope"])
    adapter.scope = dict(scope)
    run.fetched_count = 3
    run.save(update_fields=["fetched_count"])
    assert not adapter._tiktok_history_terminal_orders_proof(job, 2)
    run.fetched_count = 2
    run.save(update_fields=["fetched_count"])

    other_run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="different-segment-run",
        idempotency_key="different-segment-run")
    adapter.source_run = other_run
    assert not adapter._tiktok_history_terminal_orders_proof(job, 2)
    adapter.source_run = run

    adapter.scope = dict(scope)
    foreign_tenant = Tenant.objects.create(name="foreign", code="foreign-proof")
    batch.tenant = foreign_tenant
    batch.save(update_fields=["tenant"])
    assert not adapter._tiktok_history_terminal_orders_proof(job, 2)


def test_fetch_orders_passes_unwrapped_provider_cursor_to_trusted_proof():
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    payload = {"code": 0, "data": {"total_count": 2, "next_page_token": ""}}
    client._request = Mock(return_value=payload)
    client.trusted_terminal_orders_proof = Mock(return_value=True)

    page = client.fetch_orders("provider-cursor", {
        "time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created",
    })

    assert page["records"] == [] and page["next_cursor"] == ""
    client.trusted_terminal_orders_proof.assert_called_once_with(2)


@pytest.mark.parametrize("data", [
    {"orders": "secret-order", "total_count": "secret-total", "next_page_token": "secret-token"},
    {"orders": None, "total_count": True, "next_page_token": {"secret": "secret-token"}},
    {"total_count": 2, "next_page_token": "secret-token"},
])
def test_malformed_order_diagnostic_exposes_structure_only(data):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="secret-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    client._request = Mock(return_value={"code": 0, "data": data})
    with pytest.raises(ValidationError) as caught:
        client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "updated"})
    message = str(caught.value)
    assert "missing data.orders" in message
    assert "diagnostic(" in message
    assert "secret" not in message
    assert client._request.call_count == (2 if "orders" not in data else 1)
    if "orders" not in data:
        assert client._request.call_args_list[0] == client._request.call_args_list[1]
