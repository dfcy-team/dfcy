"""Synthetic MySQL regression for the two SyncJob startup lock sites.

Run only against the isolated local test database, never a business database.
"""
from queue import Queue
from threading import Event, Thread
from time import monotonic

import pytest
import django
from django.db import OperationalError, close_old_connections, connection, transaction

from apps.accounts.models import CustomUser
from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.models import PlatformIntegrationConfig, SyncJob
from apps.integrations.sync_services import run_sync_job
from apps.integrations.tasks import run_readonly_sync_job
from apps.tenants.models import Tenant


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "mysql", reason="requires isolated MySQL"),
]


@pytest.fixture
def jobs():
    assert django.get_version() == "5.2.17"
    assert connection.vendor == "mysql", "This regression requires real MySQL, not SQLite."
    assert connection.features.has_select_for_update_of
    assert str(connection.settings_dict["NAME"]).startswith("test_synthetic_lock_scope")
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION(), @@transaction_isolation")
        version, isolation = cursor.fetchone()
    assert version == "8.4.11"
    assert isolation == "READ-COMMITTED"
    tenant = Tenant.objects.create(name="Synthetic lock fixture", code="lock-synthetic")
    user = CustomUser.objects.create_user(username="lock-synthetic", tenant=tenant)
    configs = [
        PlatformIntegrationConfig.objects.create(
            tenant=tenant, platform="mock", account_alias=f"synthetic-{index}",
            environment=PlatformIntegrationConfig.Environment.MOCK,
            status=PlatformIntegrationConfig.Status.ACTIVE, created_by=user,
        )
        for index in range(2)
    ]
    return [
        SyncJob.objects.create(
            tenant=tenant, integration_config=configs[index],
            resource_type=SyncJob.ResourceType.MOCK_RECORD,
            schedule_type=SyncJob.ScheduleType.MANUAL,
        )
        for index in (0, 0, 1)
    ]


def lock_query(job, narrowed):
    kwargs = {"of": ("self",)} if narrowed else {}
    return (SyncJob.objects.select_for_update(**kwargs)
            .select_related("integration_config", "tenant")
            .get(pk=job.pk, tenant_id=job.tenant_id))


@pytest.mark.parametrize("narrowed,target_index,expected_code", [
    (False, 1, 1205),  # Original: different jobs sharing config block.
    (False, 2, 1205),  # Original: different configs sharing tenant also block.
    (True, 1, None),   # Fixed: independent jobs sharing config can proceed.
    (True, 2, None),   # Fixed: independent jobs sharing tenant can proceed.
    (True, 0, 1205),   # Fixed: the same job still serializes.
])
def test_real_mysql_two_connection_lock_scope(jobs, narrowed, target_index, expected_code):
    started = Event()
    outcomes = Queue()

    def contender():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = 2")
            started.set()
            begin = monotonic()
            try:
                with transaction.atomic():
                    lock_query(jobs[target_index], narrowed)
                outcomes.put((None, monotonic() - begin))
            except OperationalError as exc:
                outcomes.put((exc.args[0], monotonic() - begin))
            except Exception as exc:
                outcomes.put((type(exc).__name__, monotonic() - begin))
        finally:
            connection.close()

    thread = Thread(target=contender, name="synthetic-lock-contender", daemon=True)
    with transaction.atomic():
        lock_query(jobs[0], narrowed)
        thread.start()
        assert started.wait(3), "Contender did not establish its independent connection."
        code, elapsed = outcomes.get(timeout=5)
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert code == expected_code
        if expected_code is None:
            assert elapsed < 1.5, "Independent job should not wait for the holder transaction."
        else:
            assert elapsed >= 1.5, "The blocking control must actually wait for its lock."


class StartupQueryObserved(Exception):
    pass


@pytest.mark.parametrize("entrypoint", ["execution", "scheduled"])
def test_actual_startup_entrypoint_requests_self_lock(jobs, monkeypatch, entrypoint):
    seen = []

    class StopBeforeQuery:
        def select_related(self, *relations):
            assert set(relations) == {"integration_config", "tenant"}
            return self

        def get(self, **filters):
            assert filters["pk"] == jobs[0].pk
            if entrypoint == "execution":
                assert filters["tenant_id"] == jobs[0].tenant_id
            raise StartupQueryObserved

    def observe_lock(**kwargs):
        seen.append(kwargs)
        return StopBeforeQuery()

    monkeypatch.setattr(SyncJob.objects, "select_for_update", observe_lock)
    with pytest.raises(StartupQueryObserved):
        if entrypoint == "execution":
            run_sync_job(jobs[0], adapter=MockPlatformAdapter(), idempotency_key="synthetic-observation")
        else:
            run_readonly_sync_job.run(jobs[0].pk, idempotency_key="scheduled:synthetic:1")
    assert seen == [{"of": ("self",)}]


def test_narrowed_query_keeps_tenant_filter(jobs):
    other = Tenant.objects.create(name="Other synthetic tenant", code="other-lock-synthetic")
    with transaction.atomic(), pytest.raises(SyncJob.DoesNotExist):
        (SyncJob.objects.select_for_update(of=("self",))
         .select_related("integration_config", "tenant")
         .get(pk=jobs[0].pk, tenant_id=other.pk))


def test_compiled_sql_keeps_joins_but_only_locks_syncjob(jobs):
    with transaction.atomic():
        query = (SyncJob.objects.select_for_update(of=("self",))
                 .select_related("integration_config", "tenant")
                 .filter(pk=jobs[0].pk, tenant_id=jobs[0].tenant_id))
        sql, _params = query.query.sql_with_params()
        assert "INNER JOIN `integrations_platformintegrationconfig`" in sql
        assert "INNER JOIN `tenants_tenant`" in sql
        assert sql.endswith("FOR UPDATE OF `integrations_syncjob`")
