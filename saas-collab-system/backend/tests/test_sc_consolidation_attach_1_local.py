from io import BytesIO

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from PIL import Image

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.common.exceptions import BusinessRuleViolation, IdempotencyConflict, ScopedResourceNotFound, StateConflict
from apps.consolidation.models import ConsolidationBoxAllocation, ConsolidationEvent
from apps.consolidation.services import (
    allocate_consolidation_boxes,
    release_consolidation,
    submit_consolidation_handover,
)
from apps.files.models import (
    AttachmentUploadSession,
    ControlledAttachment,
    ControlledAttachmentEvent,
    _attachment_domain_write_context,
)
from apps.files.services import (
    AttachmentScanResult,
    FakeAttachmentScanner,
    InMemoryAttachmentStorage,
    accept_attachment,
    create_attachment_upload_session,
    finalize_attachment,
    quarantine_attachment,
    record_attachment_scan_result,
    supersede_attachment,
)
from apps.packing.services import create_packing_batch
from apps.tenants.models import Tenant
from tests.test_sc_consolidation_1_local import actor, completed_box, site_and_consolidation


pytestmark = pytest.mark.django_db


def image_bytes(*, image_format="PNG", size=(4, 3), color=(30, 120, 210)):
    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format=image_format)
    return output.getvalue()


def released_allocation(tenant, user, suffix="ATT"):
    box = completed_box(tenant, user, suffix)
    _, consolidation = site_and_consolidation(tenant, user, suffix)
    consolidation, _, _ = allocate_consolidation_boxes(
        consolidation_id=consolidation.id,
        box_ids=[box.id],
        actor=user,
        expected_version=consolidation.version,
        idempotency_key=f"allocate-{suffix}",
    )
    consolidation, _, _ = release_consolidation(
        consolidation_id=consolidation.id,
        actor=user,
        expected_version=consolidation.version,
        idempotency_key=f"release-{suffix}",
    )
    return consolidation.allocations.get(), consolidation, box


def create_accepted_attachment(tenant, user, suffix="EVIDENCE", *, storage=None):
    storage = storage or InMemoryAttachmentStorage()
    allocation, consolidation, box = released_allocation(tenant, user, suffix)
    attachment, event, replayed = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key=f"upload-session-{suffix}",
        storage=storage,
    )
    assert replayed is False
    session = attachment.upload_session
    assert isinstance(session, AttachmentUploadSession)
    content = image_bytes()
    attachment, _, _ = finalize_attachment(
        actor=user,
        attachment_id=attachment.id,
        idempotency_key=f"finish-{suffix}",
        file_name="../../handover-proof.PNG",
        claimed_media_type="image/png",
        content=content,
        upload_token=session.upload_token,
        storage=storage,
    )
    attachment, _, _ = accept_attachment(
        actor=user,
        attachment_id=attachment.id,
        idempotency_key=f"scan-{suffix}",
        scanner=FakeAttachmentScanner(
            result=AttachmentScanResult(passed=True, engine="local-test", version="1")
        ),
        storage=storage,
    )
    return attachment, allocation, consolidation, box, storage


def test_controlled_attachment_lifecycle_is_scan_gated_and_submit_is_atomic():
    tenant = Tenant.objects.create(name="Attach tenant", code="attach-local")
    user = actor(tenant, "attach-local-actor")
    storage = InMemoryAttachmentStorage()
    allocation, consolidation, box = released_allocation(tenant, user, "LIFE")
    attachment, event, replayed = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="attach-upload-life",
        storage=storage,
    )
    assert replayed is False
    assert event.action == ControlledAttachmentEvent.Action.UPLOAD_SESSION
    session = attachment.upload_session
    content = image_bytes(image_format="JPEG")
    attachment, event, _ = finalize_attachment(
        actor=user,
        upload_session_id=session.id,
        idempotency_key="attach-finish-life",
        file_name=r"C:\temp\proof.jpg",
        claimed_media_type="image/jpeg",
        content=content,
        upload_token=session.upload_token,
        storage=storage,
    )
    assert attachment.state == ControlledAttachment.State.UPLOADED
    assert attachment.scan_status == ControlledAttachment.ScanStatus.PENDING
    assert attachment.file_name == "proof.jpg"
    assert attachment.storage_key and "://" not in attachment.storage_key
    assert attachment.sha256
    with pytest.raises(StateConflict):
        submit_consolidation_handover(
            consolidation_id=consolidation.id,
            allocation_id=allocation.id,
            actor=user,
            expected_version=consolidation.version,
            evidence_ids=[attachment.id],
            idempotency_key="submit-before-accept",
        )
    attachment, event, _ = record_attachment_scan_result(
        actor=user,
        attachment_id=attachment.id,
        idempotency_key="attach-scan-life",
        scanner=FakeAttachmentScanner(
            result=AttachmentScanResult(passed=True, engine="fake", version="test-1")
        ),
        storage=storage,
    )
    assert attachment.state == ControlledAttachment.State.ACCEPTED
    assert event.action == ControlledAttachmentEvent.Action.ACCEPT
    submit_expected_version = consolidation.version
    allocation, event, replayed = submit_consolidation_handover(
        consolidation_id=consolidation.id,
        allocation_id=allocation.id,
        actor=user,
        expected_version=submit_expected_version,
        evidence_ids=[attachment.id],
        idempotency_key="submit-life",
        handover_method="photo",
        handover_reference="REF-1",
    )
    assert replayed is False
    assert allocation.state == ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED
    assert event.action == ConsolidationEvent.Action.HANDOVER_SUBMIT
    assert allocation.handover_evidence_id == str(attachment.id)
    assert allocation.evidence_ids == [attachment.id]
    replay, _, replayed = submit_consolidation_handover(
        consolidation_id=consolidation.id,
        allocation_id=allocation.id,
        actor=user,
        expected_version=submit_expected_version,
        evidence_ids=[attachment.id],
        idempotency_key="submit-life",
        handover_method="photo",
        handover_reference="REF-1",
    )
    assert replay.state == ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED
    assert replayed is True


def test_binding_is_server_derived_and_cross_supplier_is_not_visible():
    tenant = Tenant.objects.create(name="Attach supplier scope", code="attach-scope")
    internal = actor(tenant, "attach-scope-internal")
    allocation, _, _ = released_allocation(tenant, internal, "SCOPE")
    supplier_id = allocation.supplier_id_snapshot
    external = CustomUser.objects.create_user(
        username="attach-scope-external",
        tenant=tenant,
        user_type=CustomUser.UserType.EXTERNAL,
    )
    ExternalUserProfile.objects.create(user=external, tenant=tenant, supplier_id=supplier_id + 999)
    with pytest.raises(ScopedResourceNotFound):
        create_attachment_upload_session(
            actor=external,
            allocation_id=allocation.id,
            idempotency_key="cross-supplier-upload",
        )
    other_tenant = Tenant.objects.create(name="Other attach tenant", code="attach-other")
    other_user = actor(other_tenant, "attach-other-actor")
    with pytest.raises(ScopedResourceNotFound):
        create_attachment_upload_session(
            actor=other_user,
            allocation_id=allocation.id,
            idempotency_key="cross-tenant-upload",
        )


def test_invalid_magic_and_quarantine_fail_closed():
    tenant = Tenant.objects.create(name="Attach invalid", code="attach-invalid")
    user = actor(tenant, "attach-invalid-actor")
    allocation, _, _ = released_allocation(tenant, user, "INVALID")
    storage = InMemoryAttachmentStorage()
    attachment, _, _ = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="upload-invalid",
        storage=storage,
    )
    attachment, _, _ = finalize_attachment(
        actor=user,
        attachment_id=attachment.id,
        idempotency_key="finish-invalid",
        file_name="payload.png",
        claimed_media_type="image/png",
        content=b"<html>not an image</html>",
        storage=storage,
    )
    assert attachment.state == ControlledAttachment.State.REJECTED
    with pytest.raises(StateConflict):
        accept_attachment(actor=user, attachment_id=attachment.id, idempotency_key="accept-invalid")

    quarantine, _, _ = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="upload-quarantine",
        storage=storage,
    )
    quarantine, _, _ = finalize_attachment(
        actor=user,
        attachment_id=quarantine.id,
        idempotency_key="finish-quarantine",
        file_name="quarantine.png",
        claimed_media_type="image/png",
        content=image_bytes(),
        storage=storage,
    )
    quarantine, _, _ = quarantine_attachment(
        actor=user,
        attachment_id=quarantine.id,
        idempotency_key="scan-quarantine",
        scanner=FakeAttachmentScanner(
            result=AttachmentScanResult(
                passed=False,
                quarantined=True,
                engine="fake",
                version="test-1",
                rejection_code="timeout",
            )
        ),
        storage=storage,
    )
    assert quarantine.state == ControlledAttachment.State.QUARANTINED
    with pytest.raises(StateConflict):
        submit_consolidation_handover(
            consolidation_id=allocation.consolidation_id,
            allocation_id=allocation.id,
            actor=user,
            expected_version=allocation.consolidation.version,
            evidence_ids=[quarantine.id],
            idempotency_key="submit-quarantine",
        )


def test_supersede_and_orm_bypass_are_audited():
    tenant = Tenant.objects.create(name="Attach supersede", code="attach-supersede")
    user = actor(tenant, "attach-supersede-actor")
    first, allocation, consolidation, box, storage = create_accepted_attachment(tenant, user, "SUPER1")
    second, _, _ = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="upload-super2",
        storage=storage,
    )
    second, _, _ = finalize_attachment(
        actor=user,
        attachment_id=second.id,
        idempotency_key="finish-super2",
        file_name="replacement.png",
        claimed_media_type="image/png",
        content=image_bytes(color=(220, 30, 40)),
        upload_token=second.upload_session.upload_token,
        storage=storage,
    )
    second, _, _ = accept_attachment(
        actor=user,
        attachment_id=second.id,
        idempotency_key="scan-super2",
        scanner=FakeAttachmentScanner(
            result=AttachmentScanResult(passed=True, engine="local-test", version="1")
        ),
        storage=storage,
    )
    old, event, replayed = supersede_attachment(
        actor=user,
        attachment_id=first.id,
        replacement_attachment_id=second.id,
        idempotency_key="supersede-1",
        reason="Corrected photo",
    )
    assert replayed is False
    assert old.state == ControlledAttachment.State.SUPERSEDED
    assert old.superseded_by_id == second.id
    assert event.action == ControlledAttachmentEvent.Action.SUPERSEDE
    with pytest.raises(DjangoValidationError):
        ControlledAttachment.objects.filter(pk=second.id).update(file_name="bypass.png")
    with pytest.raises(DjangoValidationError):
        ControlledAttachment.objects.bulk_create([])
    with pytest.raises(DjangoValidationError):
        ControlledAttachmentEvent.objects.filter(pk=event.id).delete()


def test_same_key_replay_and_payload_conflict_are_deterministic():
    tenant = Tenant.objects.create(name="Attach idempotency", code="attach-idem")
    user = actor(tenant, "attach-idem-actor")
    allocation, _, _ = released_allocation(tenant, user, "IDEM")
    first, _, replayed = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="idem-upload",
    )
    second, _, replayed = create_attachment_upload_session(
        actor=user,
        allocation_id=allocation.id,
        idempotency_key="idem-upload",
    )
    assert second.id == first.id
    assert replayed is True
    with pytest.raises(IdempotencyConflict):
        create_attachment_upload_session(
            actor=user,
            allocation_id=allocation.id,
            idempotency_key="idem-upload",
            channel="miniapp",
        )
