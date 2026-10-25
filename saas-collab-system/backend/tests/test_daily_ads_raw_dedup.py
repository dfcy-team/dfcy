import uuid
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import connection, connections
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.integrations import raw_services
from apps.integrations.models import (
    AdvertisingRawPayloadReference, SharedAdvertisingRawPayload,
    SyncRawEnvelope, SyncRun,
)
from tests.test_sync_capability_gate import make_job

pytestmark = pytest.mark.django_db


@pytest.fixture
def ads(settings):
    settings.RAW_DAILY_ADS_DEDUP_ENABLED = True
    settings.RAW_DAILY_ADS_DEDUP_JOB_IDS = ()
    settings.RAW_PAYLOAD_STORAGE_ALIAS = ""
    job, authorization = make_job()
    job.resource_type = "advertising_report"
    job.save(update_fields=["resource_type"])
    adapter = SimpleNamespace(adapter_name="synthetic-ads", authorization=authorization)
    return job, adapter


def run_for(job):
    key = uuid.uuid4().hex
    return SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id=key,
                                  idempotency_key=key, status="running")


def page(value=12):
    return {"raw_responses": [{"endpoint": "/synthetic/ads", "payload": {"spend": value}}],
            "records": [{"id": "synthetic", "spend": value}], "next_cursor": ""}


def archive(ads, value=12, run=None, cursor=""):
    job, adapter = ads
    return raw_services.archive_raw_page(job, run or run_for(job), adapter, cursor, page(value))


def test_identical_pages_share_content_but_keep_each_run_and_cursor(ads):
    first = archive(ads, cursor="old")
    second = archive(ads, cursor="new")
    assert first.pk != second.pk and first.raw_ref != second.raw_ref
    assert first.sync_run_id != second.sync_run_id
    assert (first.cursor, second.cursor) == ("old", "new")
    assert first.payload == second.payload == {}
    assert SharedAdvertisingRawPayload.objects.count() == 1
    assert AdvertisingRawPayloadReference.objects.count() == 2
    assert raw_services.load_raw_payload(first) == raw_services.load_raw_payload(second)
    assert first.payload_hash == raw_services.payload_digest(raw_services.load_raw_payload(first))


def test_large_repeated_response_has_one_payload_without_losing_replay(ads):
    job, adapter = ads
    value = page()
    value["records"][0]["description"] = "synthetic" * 12500
    envelopes = [raw_services.archive_raw_page(job, run_for(job), adapter, "", value) for _ in range(10)]
    original_bytes = len(json.dumps(raw_services.load_raw_payload(envelopes[0])).encode()) * 10
    stored_bytes = sum(len(json.dumps(blob.payload).encode()) for blob in SharedAdvertisingRawPayload.objects.all())
    stored_bytes += sum(len(json.dumps(e.payload).encode()) for e in envelopes)
    assert stored_bytes < original_bytes * .11
    assert all(raw_services.load_raw_payload(e)["records"] == value["records"] for e in envelopes)


def test_changed_metrics_save_new_content(ads):
    first, second = archive(ads, 12), archive(ads, 13)
    assert SharedAdvertisingRawPayload.objects.count() == 2
    assert raw_services.load_raw_payload(first)["records"][0]["spend"] == 12
    assert raw_services.load_raw_payload(second)["records"][0]["spend"] == 13


@pytest.mark.parametrize("boundary", ["tenant", "store", "endpoint", "platform", "cursor_in_response"])
def test_sharing_never_crosses_scope_boundaries(ads, boundary):
    archive(ads)
    job, adapter = ads
    value = page()
    if boundary == "tenant":
        from apps.tenants.models import Tenant
        from apps.masterdata.models import PlatformMaster, StoreMaster
        from tests.test_phase2_sync_framework import create_user, create_sync_job
        tenant = Tenant.objects.create(name="Other", code="other-raw")
        user = create_user(tenant, "other-raw")
        job = create_sync_job(tenant, user)
        job.resource_type = "advertising_report"
        job.save(update_fields=["resource_type"])
        platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
        store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="other", name="Other")
        adapter = SimpleNamespace(adapter_name="synthetic-ads", authorization=SimpleNamespace(store_id=store.pk))
    elif boundary == "store":
        from apps.masterdata.models import StoreMaster
        store = StoreMaster.objects.create(tenant=job.tenant, platform=adapter.authorization.store.platform, code="other", name="Other")
        adapter = SimpleNamespace(adapter_name="synthetic-ads", authorization=SimpleNamespace(store_id=store.pk))
    elif boundary == "endpoint":
        value["raw_responses"][0]["endpoint"] = "/different/ads"
    elif boundary == "platform":
        job.integration_config.platform = "lazada"
    else:
        value["next_cursor"] = "next-page"
    entry = raw_services.archive_raw_page(job, run_for(job), adapter, "", value)
    assert SharedAdvertisingRawPayload.objects.count() == 2
    assert raw_services.load_raw_payload(entry)["records"] == value["records"]


def test_external_storage_path_remains_external(ads, monkeypatch):
    from tests.test_raw_payload_storage import MemoryStorage
    storage = MemoryStorage()
    monkeypatch.setattr(raw_services, "storages", {"private_raw": storage})
    with override_settings(RAW_PAYLOAD_STORAGE_ALIAS="private_raw", RAW_PAYLOAD_STORAGE_NAMESPACE="test"):
        entry = archive(ads)
        assert entry.payload_object_key
        assert raw_services.load_raw_payload(entry)["records"]
    assert not SharedAdvertisingRawPayload.objects.exists()


def test_job_allowlist_limits_rollout(ads):
    with override_settings(RAW_DAILY_ADS_DEDUP_JOB_IDS=(ads[0].pk + 1000,)):
        inline = archive(ads)
        assert inline.payload["records"]
    with override_settings(RAW_DAILY_ADS_DEDUP_JOB_IDS=(ads[0].pk,)):
        shared = archive(ads)
        assert shared.payload == {}
    assert SharedAdvertisingRawPayload.objects.count() == 1


def test_webhook_and_ads_mapping_paths_do_not_share(ads):
    from apps.integrations.models import WebhookEvent
    job, adapter = ads
    event = WebhookEvent.objects.create(tenant=job.tenant, platform="shopee", event_id="synthetic-hook",
        event_type="test", signature_status="mock_valid", processing_status="received", payload_hash="0" * 64)
    webhook = raw_services.archive_webhook_payload(event, {"synthetic": True})
    assert webhook.payload["payload"] == {"synthetic": True}
    mapped_job = SimpleNamespace(tenant=job.tenant, tenant_id=job.tenant_id, pk=job.pk,
        integration_config=job.integration_config, resource_type="advertising_report", ads_mapping_id=123,
        ads_mapping=SimpleNamespace(store_id=adapter.authorization.store_id))
    mapped = raw_services.archive_raw_page(mapped_job, run_for(job), adapter, "", page())
    assert mapped.payload["records"]
    assert not SharedAdvertisingRawPayload.objects.exists()


def test_same_run_pages_keep_sequence(ads):
    run = run_for(ads[0])
    first, second = archive(ads, run=run), archive(ads, run=run)
    assert (first.sequence, second.sequence) == (1, 2)
    assert SharedAdvertisingRawPayload.objects.count() == 1


def test_replay_uses_shared_records_even_after_writes_disabled(ads):
    entry = archive(ads)
    replay = SimpleNamespace(validate_configuration=lambda job: None, bind_run=lambda run: None,
        normalize_record=lambda record: record, validate_record=lambda record: True,
        persist_record=lambda job, record: {"action": "updated"})
    with override_settings(RAW_DAILY_ADS_DEDUP_ENABLED=False):
        assert raw_services.replay_raw_envelope(entry, replay)["updated"] == 1
        inline = archive(ads)
        assert inline.payload["records"] and SharedAdvertisingRawPayload.objects.count() == 1


@pytest.mark.parametrize("excluded", ["sales", "history", "no_store"])
def test_ineligible_paths_remain_inline(ads, excluded):
    job, adapter = ads
    run = run_for(job)
    if excluded == "sales":
        job.resource_type = "sales_order"
    elif excluded == "history":
        run.history_segment_id = 999  # In-memory dispatch boundary; no fake FK persisted.
    else:
        adapter.authorization = None
    entry = raw_services.archive_raw_page(job, run, adapter, "", page())
    assert entry.payload["records"]
    assert not SharedAdvertisingRawPayload.objects.exists()


def test_atomic_failure_does_not_leave_blob_or_envelope(ads):
    run = run_for(ads[0])
    with patch.object(AdvertisingRawPayloadReference.objects, "create", side_effect=RuntimeError("synthetic failure")):
        with pytest.raises(RuntimeError):
            archive(ads, run=run)
    assert not SharedAdvertisingRawPayload.objects.exists()
    assert not SyncRawEnvelope.objects.exists()


@pytest.mark.parametrize("field,value", [("tenant_id", 999), ("store_id", 999),
    ("endpoint", "/different"), ("platform", "other"), ("payload_hash", "0" * 64),
    ("payload", {"tampered": True}), ("payload_storage_alias", "unexpected"),
    ("schema_version", "raw-envelope.shared.v2")])
def test_shared_reader_fails_closed_on_envelope_context_damage(ads, field, value):
    entry = archive(ads)
    setattr(entry, field, value)
    with pytest.raises(ValidationError):
        raw_services.load_raw_payload(entry)


def test_missing_reference_fails_closed(ads):
    entry = archive(ads)
    # SQL only to simulate corruption; production ORM deletion remains forbidden.
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM integrations_advertisingrawpayloadreference WHERE envelope_id=%s", [entry.pk])
    with pytest.raises(ValidationError):
        raw_services.load_raw_payload(SyncRawEnvelope.objects.get(pk=entry.pk))


def test_hash_collision_never_reuses_different_payload(ads):
    archive(ads)
    digest = SharedAdvertisingRawPayload.objects.get().payload_hash
    with patch.object(raw_services, "payload_digest", return_value=digest):
        with pytest.raises(ValidationError):
            archive(ads, 999)
    assert SyncRawEnvelope.objects.count() == 1


def test_shared_models_are_immutable(ads):
    archive(ads)
    for model in (SharedAdvertisingRawPayload, AdvertisingRawPayloadReference):
        obj = model.objects.get()
        with pytest.raises(ModelValidationError):
            obj.save()
        with pytest.raises(ModelValidationError):
            obj.delete()
        with pytest.raises(ModelValidationError):
            model.objects.all().delete()


def test_migration_reverse_guard_rejects_shared_data(ads):
    import importlib
    from django.apps import apps
    migration = importlib.import_module("apps.integrations.migrations.0054_daily_ads_shared_raw")
    editor = SimpleNamespace(connection=connection)
    migration.prevent_shared_payload_loss(apps, editor)
    archive(ads)
    with pytest.raises(RuntimeError, match="Cannot reverse"):
        migration.prevent_shared_payload_loss(apps, editor)


@pytest.mark.django_db(transaction=True)
def test_mysql_concurrent_runs_create_one_blob(ads):
    if connection.vendor != "mysql":
        pytest.skip("MySQL unique-key race acceptance runs separately")
    job, adapter = ads
    runs = [run_for(job).pk for _ in range(4)]
    barrier = Barrier(4)

    def write(run_id):
        connections.close_all()
        try:
            run = SyncRun.objects.select_related("sync_job__tenant", "sync_job__integration_config").get(pk=run_id)
            barrier.wait(timeout=15)
            result = raw_services.archive_raw_page(run.sync_job, run, adapter, "", page())
            return result.pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(write, runs))
    assert len(set(ids)) == 4
    assert SharedAdvertisingRawPayload.objects.count() == 1
    assert AdvertisingRawPayloadReference.objects.count() == 4
    assert all(raw_services.load_raw_payload(e)["records"] for e in SyncRawEnvelope.objects.filter(pk__in=ids))
