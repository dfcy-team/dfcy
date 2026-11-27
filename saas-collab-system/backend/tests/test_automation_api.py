import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.automation import TaskList, RunList

def request(view, user, **params):
    req = APIRequestFactory().get("/api/internal/automation/tasks/", params)
    force_authenticate(req, user=user)
    return view.as_view()(req)

def user(superuser=True):
    return SimpleNamespace(is_authenticated=True, is_active=True, user_type="internal", is_superuser=superuser, tenant_id=37)

def test_denies_non_admin_before_loading_catalogue():
    with patch("apps.accounts.automation.catalogue") as catalogue:
        assert request(TaskList, user(False)).status_code == 403
        catalogue.assert_not_called()

def test_run_query_is_tenant_scoped():
    with patch("apps.accounts.automation.SyncRun") as model:
        model.objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []
        assert request(RunList, user(), source="sync_job").status_code == 200
        model.objects.filter.assert_called_once_with(tenant_id=37)

def test_flash_query_is_tenant_scoped():
    with patch("apps.accounts.automation.Batch") as batch:
        batch.objects.filter.return_value.select_related.return_value.filter.return_value.order_by.return_value.__getitem__.return_value = []
        response = request(RunList, user(), task_id="flash:00000000-0000-0000-0000-000000000001")
        assert response.status_code == 200
        assert batch.objects.filter.call_args.kwargs["tenant_id"] == 37

def test_pagination_caps_page_size():
    with patch("apps.accounts.automation.catalogue", return_value=[]):
        assert request(TaskList, user(), page_size=1000).status_code == 400

def test_import_roundtrip_and_rejects_unknown_fields(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    target = tmp_path / "observations.json"
    row = dict(id="abc", observed_at=timezone.now().isoformat(), enabled=True, state="idle", schedule="姣忓ぉ08:10")
    snapshot.write_text(json.dumps(dict(tasks=[row])), encoding="utf-8")
    with override_settings(AUTOMATION_OBSERVATIONS_FILE=str(target)):
        call_command("import_automation_observations", str(snapshot))
        assert json.loads(target.read_text())["tasks"] == [row]
        row["command"] = "forbidden"
        snapshot.write_text(json.dumps(dict(tasks=[row])), encoding="utf-8")
        with pytest.raises(CommandError):
            call_command("import_automation_observations", str(snapshot))
        assert "command" not in json.loads(target.read_text())["tasks"][0]


def test_import_rejects_future_and_missing_file(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    row = dict(id="abc", observed_at=(timezone.now() + timezone.timedelta(days=1)).isoformat(), enabled=True, state="idle")
    snapshot.write_text(json.dumps(dict(tasks=[row])), encoding="utf-8")
    with override_settings(AUTOMATION_OBSERVATIONS_FILE=str(tmp_path / "target.json")):
        with pytest.raises(CommandError):
            call_command("import_automation_observations", str(snapshot))
        with pytest.raises(CommandError):
            call_command("import_automation_observations", str(tmp_path / "missing.json"))


@pytest.mark.django_db
def test_real_tenant_catalogue_and_flash_history():
    from datetime import time
    from apps.tenants.models import Tenant
    from apps.accounts.models import CustomUser
    models = pytest.importorskip("apps.flash_sales.models")
    Plan, Batch = models.Plan, models.Batch
    from apps.accounts.automation import catalogue, TaskDetail
    actors = []
    for code in ("auto-a", "auto-b"):
        tenant = Tenant.objects.create(name=code, code=code)
        actor = CustomUser.objects.create_user(username=code, tenant=tenant,
            user_type="internal", is_superuser=True)
        plan = Plan.objects.create(tenant=tenant, actor=actor, name=code,
            kind="daily", local_time=time(19, 30), enabled=True)
        Batch.objects.create(tenant=tenant, actor=actor, plan=plan,
            request_id=code, payload_hash="a"*64, source="scheduled")
        actors.append((actor, plan))
    actor, plan = actors[0]
    rows = catalogue(actor)
    flashes = [row for row in rows if row["source"] == "flash"]
    assert [row["id"] for row in flashes] == [f"flash:{plan.pk}"]
    result = request(RunList, actor, source="flash")
    assert result.status_code == 200
    assert result.data["data"]["count"] == 1
    assert result.data["data"]["results"][0]["name"] == "auto-a"
    req = APIRequestFactory().get("/")
    force_authenticate(req, user=actor)
    response = TaskDetail.as_view()(req, task_id=f"flash:{actors[1][1].pk}")
    assert response.status_code == 404


@pytest.mark.django_db
def test_external_observed_state_and_history(tmp_path):
    from apps.accounts.automation import catalogue
    path = tmp_path / "observed.json"
    now = timezone.now().isoformat()
    row = dict(id="abc", observed_at=now, enabled=True, state="idle", runs=[
        dict(id="abc-1", tenant_id=37, status="partial", started_at=now, finished_at=now, result="参考等级")])
    path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")
    with override_settings(AUTOMATION_OBSERVATIONS_FILE=str(path)):
        task = next(row for row in catalogue(user()) if row["id"] == "external:abc")
        assert not task["stale"]
        result = request(RunList, user(), source="cron", task_id="external:abc")
        assert result.data["data"]["results"][0]["status"] == "partial"
    row["observed_at"] = (timezone.now() - timezone.timedelta(hours=1)).isoformat()
    path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")
    with override_settings(AUTOMATION_OBSERVATIONS_FILE=str(path)):
        task = next(row for row in catalogue(user()) if row["id"] == "external:abc")
        assert task["stale"] and task["state"] == "unknown"


@pytest.mark.django_db
def test_external_business_runs_isolate_tenant_and_sort_finished(tmp_path):
    path = tmp_path / "observed.json"
    now = timezone.now()
    runs = [
        dict(id="ours", tenant_id=37, status="success", started_at=None,
             finished_at=now.isoformat(), result="own result"),
        dict(id="other", tenant_id=99, status="failed", started_at=None,
             finished_at=now.isoformat(), result="secret result"),
        dict(id="older", tenant_id=37, status="success", started_at=None,
             finished_at=(now-timezone.timedelta(hours=1)).isoformat(), result="older"),
    ]
    row = dict(id="abc", observed_at=now.isoformat(), enabled=True,
               state="idle", last_result="secret aggregate", runs=runs)
    path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")
    from apps.accounts.automation import catalogue, validate_observations
    with override_settings(AUTOMATION_OBSERVATIONS_FILE=str(path)):
        response = request(RunList, user(), task_id="external:abc")
        assert [item["result"] for item in response.data["data"]["results"]] == ["own result", "older"]
        task = next(item for item in catalogue(user()) if item["id"] == "external:abc")
        assert task["last_result"] is None
    runs[0]["tenant_id"] = True
    with pytest.raises(ValueError):
        validate_observations({"tasks": [row]})


def test_schedule_shape_and_secret_allowlist():
    from apps.accounts.automation import safe_sync_schedule
    for value in (None, [], {"schedule": None}, {"schedule": []}):
        assert safe_sync_schedule(value, "daily") == {"type": "daily"}
    assert safe_sync_schedule({"schedule": {"timezone": "UTC", "token": "secret"}}, "daily") == {"timezone": "UTC"}


def test_invalid_sync_identifier_returns_400():
    for value in ("sync:0", "sync:１２", "sync:-1", "sync:9999999999999999999999"):
        with patch("apps.accounts.automation.SyncRun"), patch("apps.accounts.automation.Batch"):
            assert request(RunList, user(), task_id=value).status_code == 400


def test_unknown_enabled_and_beat_schedule():
    from apps.accounts.automation import validate_observations, catalogue
    from django.test import override_settings
    row = dict(id="beat:test-job", observed_at=timezone.now().isoformat(),
               enabled=None, state="unknown", schedule="every 90 seconds")
    with override_settings(CELERY_BEAT_SCHEDULE={"test-job": {"schedule": 30}}):
        assert validate_observations({"tasks": [row]})[row["id"]]["enabled"] is None
        with patch("apps.accounts.automation.observations", return_value={row["id"]: row}), patch("apps.accounts.automation.SyncJob") as model, patch("apps.accounts.automation.Plan", None):
            model.objects.filter.return_value.select_related.return_value.annotate.return_value.count.return_value = 0
            model.objects.filter.return_value.select_related.return_value.annotate.return_value.order_by.return_value.iterator.return_value = []
            task = catalogue(user())[0]
            assert task["schedule"] == "every 90 seconds" and task["enabled"] is None
