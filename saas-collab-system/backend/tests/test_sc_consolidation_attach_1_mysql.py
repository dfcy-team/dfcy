"""Real-MySQL concurrency gate for SC-CONSOLIDATION-ATTACH-1.

The module is intentionally skipped on SQLite.  The local gate starts an
isolated MySQL 8.4 instance and runs this file with ``DB_ENGINE`` set to the
MySQL backend; no production storage or scanner is involved.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection

from apps.consolidation.models import ConsolidationBoxAllocation, ConsolidationEvent
from apps.consolidation.services import submit_consolidation_handover
from apps.files.models import ControlledAttachment, ControlledAttachmentEvent
from apps.files.services import (
    InMemoryAttachmentStorage,
    accept_attachment,
    create_attachment_upload_session,
    finalize_attachment,
    record_attachment_scan_result,
)
from apps.packing.models import PackingStandardVersion, _packing_domain_write_context
from apps.tenants.models import Tenant
from tests.test_sc_consolidation_1_local import actor
from tests.test_sc_consolidation_attach_1_local import (
    create_accepted_attachment,
    image_bytes,
    released_allocation,
)


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "mysql", reason="SC attach MySQL gate requires a real MySQL connection"),
]


@pytest.fixture(autouse=True)
def packing_standard():
    # ``--nomigrations`` is useful when the repository's historical products
    # migration is intentionally isolated; retain the same deterministic seed.
    if not PackingStandardVersion.objects.filter(code="packing-v1", version=1).exists():
        with _packing_domain_write_context():
            PackingStandardVersion.objects.create(
                code="packing-v1",
                version=1,
                title="Packing v1",
                rules={
                    "empty_box_forbidden": True,
                    "exact_completion_required": True,
                    "mixed_box_label_items_required": True,
                },
            )


def _thread_call(function, *args, **kwargs):
    """Give every worker a fresh Django connection and close it afterwards."""
    close_old_connections()
    try:
        return function(*args, **kwargs)
    finally:
        close_old_connections()


def _parallel(function, count=2):
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(_thread_call, function) for _ in range(count)]
        return [future.result() for future in futures]


def test_mysql_same_key_finalize_and_scan_have_one_event_and_stable_replay():
    tenant = Tenant.objects.create(name="Attach mysql idem", code="attach-mysql-idem")
    user = actor(tenant, "attach-mysql-idem-actor")
    allocation, _, _ = released_allocation(tenant, user, "MYSQL-IDEM")
    storage = InMemoryAttachmentStorage()
    attachment, _, _ = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="mysql-upload-session",
        storage=storage,
    )
    session = attachment.upload_session
    content = image_bytes(image_format="JPEG")

    def finish():
        worker = type(user).objects.get(pk=user.pk)
        return finalize_attachment(
            actor=worker,
            attachment_id=attachment.id,
            idempotency_key="mysql-finish-same-key",
            file_name="proof.jpg",
            claimed_media_type="image/jpeg",
            content=content,
            upload_token=session.upload_token,
            storage=storage,
        )

    finished = _parallel(finish)
    assert sorted(bool(item[2]) for item in finished) == [False, True]
    assert ControlledAttachmentEvent.objects.filter(
        attachment_id=attachment.id,
        action=ControlledAttachmentEvent.Action.FINISH,
        idempotency_key="mysql-finish-same-key",
    ).count() == 1

    def scan():
        worker = type(user).objects.get(pk=user.pk)
        return record_attachment_scan_result(
            actor=worker,
            attachment_id=attachment.id,
            idempotency_key="mysql-scan-same-key",
            passed=True,
            scan_engine="mysql-fake",
            scan_engine_version="1",
        )

    scanned = _parallel(scan)
    assert sorted(bool(item[2]) for item in scanned) == [False, True]
    attachment.refresh_from_db()
    assert attachment.state == ControlledAttachment.State.ACCEPTED
    assert ControlledAttachmentEvent.objects.filter(
        attachment_id=attachment.id,
        action=ControlledAttachmentEvent.Action.ACCEPT,
        idempotency_key="mysql-scan-same-key",
    ).count() == 1


def test_mysql_same_key_handover_submit_changes_shipped_never_and_replays_once():
    tenant = Tenant.objects.create(name="Attach mysql submit", code="attach-mysql-submit")
    user = actor(tenant, "attach-mysql-submit-actor")
    attachment, allocation, consolidation, _, _ = create_accepted_attachment(
        tenant, user, "MYSQL-SUBMIT"
    )
    expected_version = consolidation.version

    def submit():
        worker = type(user).objects.get(pk=user.pk)
        return submit_consolidation_handover(
            consolidation_id=consolidation.id,
            allocation_id=allocation.id,
            actor=worker,
            expected_version=expected_version,
            evidence_ids=[attachment.id],
            idempotency_key="mysql-submit-same-key",
            handover_method="photo",
            handover_reference="MYSQL-REF",
        )

    submitted = _parallel(submit)
    assert sorted(bool(item[2]) for item in submitted) == [False, True]
    allocation.refresh_from_db()
    assert allocation.state == ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED
    assert ConsolidationEvent.objects.filter(
        consolidation_id=consolidation.id,
        action=ConsolidationEvent.Action.HANDOVER_SUBMIT,
        idempotency_key="mysql-submit-same-key",
    ).count() == 1
    # Handover confirmation is deliberately not shipment accounting.
    assert not hasattr(allocation, "shipped_quantity")


def test_mysql_constraints_and_orm_bypass_are_enforced():
    tenant = Tenant.objects.create(name="Attach mysql constraints", code="attach-mysql-constraints")
    user = actor(tenant, "attach-mysql-constraints-actor")
    attachment, allocation, _, _, _ = create_accepted_attachment(tenant, user, "MYSQL-CONSTRAINT")
    with pytest.raises(Exception):
        ControlledAttachment.objects.filter(pk=attachment.id).update(state=ControlledAttachment.State.DELETED)
    with pytest.raises(Exception):
        ControlledAttachmentEvent.objects.filter(pk=ControlledAttachmentEvent.objects.filter(
            attachment_id=attachment.id,
        ).first().id).delete()
    attachment.refresh_from_db()
    assert attachment.state == ControlledAttachment.State.ACCEPTED
    assert allocation.tenant_id == tenant.id
