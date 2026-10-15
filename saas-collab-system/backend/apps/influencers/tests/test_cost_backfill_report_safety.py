from contextlib import contextmanager
from decimal import Decimal
from io import StringIO
import json
import os
import stat

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit.models import OperationLog
from apps.influencers.attribution import create_sample_attribution_snapshot
from apps.influencers.management.commands import backfill_sample_confirmed_costs as module
from apps.influencers.management.commands import reprice_sample_confirmed_costs as reprice_module
from apps.influencers.models import BdSampleAttributionSnapshot, SampleFulfillment, SampleItem
from apps.influencers.tests.test_current_sample_costs import legacy_sample
from apps.influencers.tests.test_pending_cost_backfill import setup as make_sample


pytestmark = pytest.mark.django_db


def invoke(user, **options):
    command = module.Command()
    output = StringIO()
    call_command(command, tenant_id=user.tenant_id, actor_id=user.pk, stdout=output, **options)
    return command.result, output.getvalue()


def cost_state(tenant):
    return {
        "items": list(SampleItem.objects.filter(tenant=tenant).order_by("pk").values()),
        "samples": list(SampleFulfillment.objects.filter(tenant=tenant).order_by("pk").values()),
        "snapshots": list(BdSampleAttributionSnapshot.objects.filter(tenant=tenant).order_by("pk").values()),
        "audit": list(OperationLog.objects.filter(tenant=tenant).order_by("pk").values()),
    }


def assert_no_business_writes(queries):
    assert not [row for row in queries if row["sql"].lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE "))]


@pytest.mark.parametrize("apply", [False, True])
def test_existing_report_is_unchanged_and_costs_are_not_written(tmp_path, apply):
    tenant, user, *_ = make_sample("report-existing")
    path = tmp_path / "report.json"
    path.write_text("previous report", encoding="utf-8")
    before = cost_state(tenant)
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises((CommandError, OSError)) as error:
            invoke(user, apply=apply, report_path=str(path))
    assert_no_business_writes(queries)
    assert isinstance(error.value, CommandError) and "report" in str(error.value)
    assert path.read_text(encoding="utf-8") == "previous report"
    assert cost_state(tenant) == before


def test_missing_report_directory_prevents_cost_writes(tmp_path):
    tenant, user, *_ = make_sample("report-missing-directory")
    before = cost_state(tenant)
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(CommandError, match="report"):
            invoke(user, apply=True, report_path=str(tmp_path / "missing" / "report.json"))
    assert_no_business_writes(queries)
    assert cost_state(tenant) == before


def test_permission_denied_report_prevents_cost_writes(tmp_path, monkeypatch):
    tenant, user, *_ = make_sample("report-denied")
    before = cost_state(tenant)
    def refuse(*args, **kwargs):
        raise PermissionError("synthetic non-writable directory")
    monkeypatch.setattr(module.os, "open", refuse)
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(CommandError, match="report"):
            invoke(user, apply=True, report_path=str(tmp_path / "report.json"))
    assert_no_business_writes(queries)
    assert cost_state(tenant) == before


def test_report_exists_before_first_cost_write_and_matches_success_receipt(tmp_path):
    tenant, user, _, parent, item, _, snapshot = make_sample("report-success")
    path = tmp_path / "report.json"
    writes = []
    def check_report(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ")):
            assert path.is_file()
            writes.append(sql.split()[0])
        return execute(sql, params, many, context)
    with connection.execute_wrapper(check_report):
        result, output = invoke(user, apply=True, report_path=str(path))
    assert writes and "applied=1" in output
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert result["counts"]["applied"] == 1
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    item.refresh_from_db(); parent.refresh_from_db(); snapshot.refresh_from_db()
    assert item.cost_amount == parent.calculated_cost == snapshot.cost_amount
    assert item.cost_amount is not None
    assert OperationLog.objects.filter(tenant=tenant, action="backfill_sample_confirmed_cost").count() == 1


@pytest.mark.parametrize("stage", ["serialize", "flush", "fsync", "close"])
def test_late_report_failure_rolls_back_all_samples_and_audits(tmp_path, monkeypatch, stage):
    tenant, user, sku, parent, *_ = make_sample("report-late-" + stage)
    second = SampleFulfillment.objects.create(
        tenant=tenant, fulfillment_no="REPORT-SECOND", request_key="REPORT-SECOND", request_hash="r" * 64,
        store=parent.store, owner=user, influencer=parent.influencer, sample_sent_at=parent.sample_sent_at,
    )
    SampleItem.objects.create(tenant=tenant, fulfillment=second, requested_sku=sku.sku_code, site_code="PH", quantity=1)
    create_sample_attribution_snapshot(
        tenant=tenant, fulfillment=second, store=second.store, owner=user, influencer=second.influencer,
    )
    before = cost_state(tenant)
    real_fdopen = module.os.fdopen
    real_dump = module.json.dump
    visited = []
    class ReportStream:
        def __init__(self, stream):
            self.stream = stream
        def write(self, value):
            return self.stream.write(value)
        def fileno(self):
            return self.stream.fileno()
        def flush(self):
            if stage == "flush":
                raise OSError("synthetic report flush failure")
            return self.stream.flush()
        def close(self):
            self.stream.close()
            if stage == "close":
                raise OSError("synthetic report close failure")
    @contextmanager
    def open_report(*args, **kwargs):
        with real_fdopen(*args, **kwargs) as stream:
            yield ReportStream(stream)
    def dump(value, stream, **kwargs):
        assert value["counts"]["applied"] == 2
        assert SampleItem.objects.filter(tenant=tenant, cost_amount__isnull=False).count() == 2
        visited.append(stage)
        if stage == "serialize":
            raise OSError("synthetic report serialization failure")
        return real_dump(value, stream, **kwargs)
    def fsync(_descriptor):
        raise OSError("synthetic report fsync failure")
    monkeypatch.setattr(module.os, "fdopen", open_report)
    monkeypatch.setattr(module.json, "dump", dump)
    if stage == "fsync":
        monkeypatch.setattr(module.os, "fsync", fsync)
    output = StringIO()
    command = module.Command()
    with pytest.raises(CommandError, match="report"):
        call_command(command, tenant_id=tenant.pk, actor_id=user.pk, apply=True,
                     report_path=str(tmp_path / "failed.json"), stdout=output)
    assert visited == [stage]
    assert cost_state(tenant) == before
    assert command.result is None and output.getvalue() == ""


def test_empty_batch_still_writes_a_complete_preview_receipt(tmp_path):
    _, user, _, _, item, *_ = make_sample("report-empty")
    path = tmp_path / "empty.json"
    result, output = invoke(user, report_path=str(path), after_item_id=item.pk)
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert result["scanned"] == 0 and result["rows"] == [] and "scanned=0" in output


@pytest.mark.parametrize("stage", ["fsync", "close"])
def test_reprice_late_report_failure_rolls_back_batch_and_audits(tmp_path, monkeypatch, stage):
    tenant, user, _, parent, item, _, snapshot = legacy_sample()
    plan_path = tmp_path / "reviewed-plan.json"
    planner = reprice_module.Command()
    call_command(planner, tenant_id=tenant.pk, actor_id=user.pk,
                 report_path=str(plan_path), stdout=StringIO())
    before = cost_state(tenant)
    real_fdopen = reprice_module.os.fdopen

    class ReportStream:
        def __init__(self, stream):
            self.stream = stream

        def write(self, value):
            return self.stream.write(value)

        def fileno(self):
            return self.stream.fileno()

        def flush(self):
            return self.stream.flush()

        def close(self):
            self.stream.close()

    @contextmanager
    def open_report(*args, **kwargs):
        wrapped = ReportStream(real_fdopen(*args, **kwargs))
        try:
            yield wrapped
        finally:
            wrapped.close()
            if stage == "close":
                raise OSError("synthetic report context-exit failure")

    def fsync(_descriptor):
        raise OSError("synthetic report fsync failure")

    monkeypatch.setattr(reprice_module.os, "fdopen", open_report)
    if stage == "fsync":
        monkeypatch.setattr(reprice_module.os, "fsync", fsync)

    output = StringIO()
    command = reprice_module.Command()
    with pytest.raises(CommandError, match="report"):
        call_command(command, tenant_id=tenant.pk, actor_id=user.pk, apply=True,
                     expected_plan=str(plan_path), report_path=str(tmp_path / "failed.json"), stdout=output)

    # The direct stream close can succeed; the failing context-exit finalizer must
    # still run before atomic exits so these writes remain rollback-able.
    assert cost_state(tenant) == before
    assert command.result is None and output.getvalue() == ""
    item.refresh_from_db(); parent.refresh_from_db(); snapshot.refresh_from_db()
    assert item.cost_amount == Decimal("2") and parent.calculated_cost == Decimal("9")
    assert snapshot.cost_amount == Decimal("3")
