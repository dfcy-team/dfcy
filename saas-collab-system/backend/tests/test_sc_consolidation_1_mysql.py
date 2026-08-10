"""MySQL-only consolidation slot/constraint smoke tests.

The same behavioural matrix is exercised on SQLite in
``test_sc_consolidation_1_local.py``.  These tests are skipped on the normal
developer SQLite connection and are enabled by the isolated MySQL gate.
"""

import pytest
from django.db import connection
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.consolidation.models import ConsolidationEvent, ConsolidationSite
from apps.consolidation.services import allocate_consolidation_boxes, create_consolidation_site, create_loose_cargo_consolidation
from apps.common.exceptions import StateConflict
from tests.test_sc_consolidation_1_local import actor, completed_box, packing_standard, site_and_consolidation
from apps.tenants.models import Tenant


pytestmark = [pytest.mark.django_db(transaction=True)]


def _mysql_only():
    if connection.vendor != "mysql":
        pytest.skip("SC-CONSOLIDATION-1 MySQL gate test")


def test_mysql_same_box_has_one_active_consolidation_slot(packing_standard):
    _mysql_only()
    tenant = Tenant.objects.create(name="Consolidation MySQL slot", code="con-mysql-slot")
    user = actor(tenant, "con-mysql-slot-actor")
    box = completed_box(tenant, user, "MYSQLSLOT")
    _, first = site_and_consolidation(tenant, user, "MS1")
    _, second = site_and_consolidation(tenant, user, "MS2")
    first, _, _ = allocate_consolidation_boxes(
        consolidation_id=first.id, box_ids=[box.id], actor=user,
        expected_version=first.version, idempotency_key="mysql-slot-1",
    )
    with pytest.raises(StateConflict):
        allocate_consolidation_boxes(
            consolidation_id=second.id, box_ids=[box.id], actor=user,
            expected_version=second.version, idempotency_key="mysql-slot-2",
        )
    assert box.consumptions.filter(active_guard=True).count() == 1
    replay, event, replayed = allocate_consolidation_boxes(
        consolidation_id=first.id, box_ids=[box.id], actor=user,
        expected_version=1, idempotency_key="mysql-slot-1",
    )
    assert replayed is True
    assert event.action == ConsolidationEvent.Action.ALLOCATE
    assert replay.id == first.id


def test_mysql_model_write_gate_and_tenant_global_event_key(packing_standard):
    _mysql_only()
    tenant = Tenant.objects.create(name="Consolidation MySQL guard", code="con-mysql-guard")
    user = actor(tenant, "con-mysql-guard-actor")
    site, _, _ = create_consolidation_site(
        actor=user, site_code="MYSQL-GUARD", name="Guard", region_code="CN-SOUTH",
        idempotency_key="mysql-guard-site",
    )
    with pytest.raises(DjangoValidationError):
        ConsolidationSite.objects.filter(pk=site.id).update(name="bypass")
    with pytest.raises(DjangoValidationError):
        ConsolidationEvent.objects.bulk_create([])
    # A replay is resolved from the append-only event ledger even when the
    # caller supplies the current object's later version.
    replay, event, replayed = create_consolidation_site(
        actor=user, site_code="MYSQL-GUARD", name="Guard", region_code="CN-SOUTH",
        idempotency_key="mysql-guard-site",
    )
    assert replayed is True
    assert replay.id == site.id
    assert event.action == ConsolidationEvent.Action.SITE_CREATE
