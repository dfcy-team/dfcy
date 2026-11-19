from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.alerts.inventory_snapshot_maintenance import _prepare_country
from apps.alerts.models import InventoryWarningRun
from apps.masterdata.models import InventoryABCRun
from tests.test_supply_chain_v2_foundation import internal_user, world


@pytest.mark.django_db
def test_maintenance_queues_once_after_country_cutoff_and_retains_last_published(world):
    country = world["country"]
    actor = internal_user(world)
    local = datetime(2026, 11, 19, 8, 9, tzinfo=ZoneInfo(country.timezone))
    last = InventoryWarningRun.objects.create(
        tenant_id=actor.tenant_id, country=country, status="ready", completed_at=local - timedelta(hours=1),
    )
    InventoryWarningRun.objects.filter(pk=last.pk).update(created_at=local - timedelta(hours=1))

    _prepare_country(actor, country, local, abc_enabled=True, warning_enabled=True)
    assert not InventoryABCRun.objects.exists()
    assert InventoryWarningRun.objects.filter(status="queued").count() == 1

    later = local + timedelta(minutes=1)
    for _ in range(2):
        _prepare_country(actor, country, later, abc_enabled=True, warning_enabled=True)
    assert InventoryABCRun.objects.get().cutoff_date == later.date() - timedelta(days=1)
    assert InventoryWarningRun.objects.filter(status="queued").count() == 1
    last.refresh_from_db()
    assert last.status == "ready"
