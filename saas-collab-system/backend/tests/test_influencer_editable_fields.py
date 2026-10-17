from types import SimpleNamespace

import pytest
from django.db.models.query import QuerySet

from apps.audit.models import OperationLog
from apps.influencers.models import BdSampleAttributionSnapshot, OutreachTarget, OutreachTask, SampleFulfillment
from apps.influencers.services import (
    create_outreach_task,
    create_sample_fulfillment,
    soft_delete_outreach_task,
)
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import base_records, user_with_permissions


pytestmark = pytest.mark.django_db


@pytest.fixture
def records():
    tenant = Tenant.objects.create(name="Editable fields", code="editable-fields")
    user, client = user_with_permissions(
        tenant, "editable-fields",
        "influencers.outreach.manage", "influencers.outreach.view",
        "influencers.fulfillment.manage", "influencers.fulfillment.view",
    )
    store, influencer, task = base_records(tenant, user, "editable-fields")
    sample, _ = create_sample_fulfillment(
        user=user, request_key="synthetic-editable-fields",
        validated_data={"outreach_task": task, "influencer": influencer, "store": store},
        item_payloads=[],
    )
    task.refresh_from_db()
    return SimpleNamespace(
        tenant=tenant, user=user, client=client, store=store,
        influencer=influencer, task=task, sample=sample,
    )


def patch_task(r, payload, *, version=None):
    return r.client.patch(
        f"/api/internal/influencers/outreach-tasks/{r.task.pk}/", payload,
        format="json", HTTP_IF_MATCH=f'"{r.task.version if version is None else version}"',
    )


def patch_sample(r, payload, *, version=None):
    return r.client.patch(
        f"/api/internal/influencers/sample-fulfillments/{r.sample.pk}/", payload,
        format="json", HTTP_IF_MATCH=f'"{r.sample.version if version is None else version}"',
    )


def test_task_number_edit_retains_ids_sources_samples_and_bd_snapshot(records):
    r = records
    r.task.source = "synthetic-import"
    r.task.external_id = "source-task-279"
    r.task.save()
    old_no = r.task.task_no
    old_task = OutreachTask.objects.values().get(pk=r.task.pk)
    old_sample = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    old_target = list(OutreachTarget.objects.filter(task=r.task).values())
    old_snapshot = list(BdSampleAttributionSnapshot.objects.filter(fulfillment=r.sample).values())
    response = patch_task(r, {"task_no": "  CUSTOM-NUMBER-279  "})
    assert response.status_code == 200
    assert response.data["data"]["task_no"] == "CUSTOM-NUMBER-279"
    r.task.refresh_from_db()
    assert r.task.version == old_task["version"] + 1
    after = OutreachTask.objects.values().get(pk=r.task.pk)
    for field in old_task.keys() - {"task_no", "version", "updated_at"}:
        assert after[field] == old_task[field]
    assert SampleFulfillment.objects.values().get(pk=r.sample.pk) == old_sample
    assert list(OutreachTarget.objects.filter(task=r.task).values()) == old_target
    assert list(BdSampleAttributionSnapshot.objects.filter(fulfillment=r.sample).values()) == old_snapshot
    audit = OperationLog.objects.get(
        tenant=r.tenant, action="outreach_update", object_id=str(r.task.pk),
    )
    assert audit.before_data["task_no"] == old_no
    assert audit.after_data["task_no"] == "CUSTOM-NUMBER-279"
    detail = r.client.get(f"/api/internal/influencers/sample-fulfillments/{r.sample.pk}/")
    assert detail.data["data"]["outreach_task_no"] == "CUSTOM-NUMBER-279"
    assert r.client.get("/api/internal/influencers/outreach-tasks/", {"search": "CUSTOM-NUMBER-279"}).data["data"]["count"] == 1


@pytest.mark.parametrize("deleted", [False, True])
def test_task_number_duplicate_including_deleted_task_is_rejected_without_writes(records, deleted):
    r = records
    other = create_outreach_task(user=r.user, validated_data={"store": r.store, "owner": r.user})
    if deleted:
        soft_delete_outreach_task(user=r.user, task=other, expected_version=other.version)
    old_task = OutreachTask.objects.values().get(pk=r.task.pk)
    old_audits = OperationLog.objects.count()
    response = patch_task(r, {"task_no": other.task_no, "task_name": "Must roll back"})
    assert response.status_code == 409
    assert response.data["message"] == "任务编号已被占用，请使用其他编号。"
    assert OutreachTask.objects.values().get(pk=r.task.pk) == old_task
    assert OperationLog.objects.count() == old_audits


@pytest.mark.parametrize("value", [None, "", "   ", "X" * 81])
def test_task_number_validation(records, value):
    r = records
    before = OutreachTask.objects.values().get(pk=r.task.pk)
    assert patch_task(r, {"task_no": value}).status_code == 400
    assert OutreachTask.objects.values().get(pk=r.task.pk) == before


def test_database_number_collision_is_a_conflict_not_a_server_error(records, monkeypatch):
    r = records
    other = create_outreach_task(user=r.user, validated_data={"store": r.store, "owner": r.user})
    before = OutreachTask.objects.values().get(pk=r.task.pk)
    real_exists = QuerySet.exists
    skipped_precheck = False

    def stale_precheck(queryset):
        nonlocal skipped_precheck
        if queryset.model is OutreachTask and not skipped_precheck and other.task_no in str(queryset.query):
            skipped_precheck = True
            return False
        return real_exists(queryset)

    monkeypatch.setattr(QuerySet, "exists", stale_precheck)
    response = patch_task(r, {"task_no": other.task_no})
    assert skipped_precheck
    assert response.status_code == 409
    assert response.data["message"] == "任务编号已被占用，请使用其他编号。"
    assert OutreachTask.objects.values().get(pk=r.task.pk) == before


def test_task_number_version_conflict_and_audit_failure_roll_back(records, monkeypatch):
    r = records
    old_task = OutreachTask.objects.values().get(pk=r.task.pk)
    assert patch_task(r, {"task_no": "STALE-NUMBER"}, version=r.task.version - 1).status_code == 409
    assert OutreachTask.objects.values().get(pk=r.task.pk) == old_task

    def fail_audit(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr("apps.influencers.services._audit", fail_audit)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        patch_task(r, {"task_no": "ROLL-BACK-NUMBER"})
    assert OutreachTask.objects.values().get(pk=r.task.pk) == old_task


def test_task_number_permissions_and_tenant_isolation(records):
    r = records
    tenant = Tenant.objects.create(name="Other editable fields", code="other-editable-fields")
    foreign_user, _ = user_with_permissions(tenant, "foreign-editable", "influencers.outreach.manage")
    _, _, foreign_task = base_records(tenant, foreign_user, "foreign-editable")
    # A number used in another tenant is not reserved in this tenant.
    foreign_task.task_no = "FOREIGN-NUMBER"
    foreign_task.save()
    assert patch_task(r, {"task_no": foreign_task.task_no}).status_code == 200
    response = r.client.patch(
        f"/api/internal/influencers/outreach-tasks/{foreign_task.pk}/",
        {"task_no": "DENIED"}, format="json", HTTP_IF_MATCH=f'"{foreign_task.version}"',
    )
    assert response.status_code == 404
    _, viewer = user_with_permissions(r.tenant, "editable-viewer", "influencers.outreach.view")
    assert viewer.patch(
        f"/api/internal/influencers/outreach-tasks/{r.task.pk}/",
        {"task_no": "DENIED"}, format="json", HTTP_IF_MATCH='"1"',
    ).status_code == 403


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_terminal_task_can_only_correct_number(records, status):
    r = records
    if status == "cancelled":
        response = r.client.post(
            f"/api/internal/influencers/outreach-tasks/{r.task.pk}/status/",
            {"status": status}, format="json", HTTP_IF_MATCH=f'"{r.task.version}"',
        )
    else:
        target = OutreachTarget.objects.get(task=r.task, influencer=r.influencer)
        r.task.target_count = 1
        r.task.save()
        response = r.client.patch(
            f"/api/internal/influencers/outreach-tasks/{r.task.pk}/targets/{target.pk}/",
            {"outreach_result": "success"}, format="json", HTTP_IF_MATCH=f'"{target.version}"',
        )
    assert response.status_code == 200
    r.task.refresh_from_db()
    assert r.task.status == status
    before = OutreachTask.objects.values().get(pk=r.task.pk)
    assert patch_task(r, {"task_no": "CORRECTED-TERMINAL"}).status_code == 200
    r.task.refresh_from_db()
    after = OutreachTask.objects.values().get(pk=r.task.pk)
    for field in before.keys() - {"task_no", "version", "updated_at"}:
        assert after[field] == before[field]
    assert patch_task(r, {"task_no": "DENIED", "owner": r.user.pk}).status_code == 409
    assert OutreachTask.objects.values().get(pk=r.task.pk) == after


@pytest.mark.parametrize("link_type", ["YYJL", "PKDJ", "ZBDR", "TKOne"])
def test_linked_sample_type_edit_preserves_identifiers_and_ownership(records, link_type):
    r = records
    before = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    snapshot = BdSampleAttributionSnapshot.objects.get(fulfillment=r.sample)
    identity_fields = ["owner_id", "influencer_id", "store_id", "creator_username", "shop_abbr", "product_id", "sampled_at"]
    old_identity = {field: getattr(snapshot, field) for field in identity_fields}
    response = patch_sample(r, {"link_type": link_type})
    assert response.status_code == 200
    r.sample.refresh_from_db()
    assert r.sample.link_type == link_type
    for field in ("id", "fulfillment_no", "outreach_task_id", "outreach_target_id", "owner_id", "influencer_id", "store_id", "source", "external_id", "status"):
        assert getattr(r.sample, field if field != "id" else "pk") == before[field]
    snapshot.refresh_from_db()
    assert {field: getattr(snapshot, field) for field in identity_fields} == old_identity
    audit = OperationLog.objects.get(tenant=r.tenant, action="sample_update", object_id=str(r.sample.pk))
    assert audit.before_data["link_type"] == "DRJL"
    assert audit.after_data["link_type"] == link_type
    r.sample.full_clean()


def test_linked_sample_direct_type_is_rejected_atomically(records):
    r = records
    before = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    audit_count = OperationLog.objects.count()
    response = patch_sample(r, {"link_type": "direct", "notes": "Must not save"})
    assert response.status_code == 400
    assert "link_type" in str(response.data)
    assert SampleFulfillment.objects.values().get(pk=r.sample.pk) == before
    assert OperationLog.objects.count() == audit_count


def test_standalone_sample_can_change_type_and_return_to_direct(records):
    r = records
    r.sample, _ = create_sample_fulfillment(
        user=r.user, request_key="synthetic-standalone-edit",
        validated_data={"influencer": r.influencer, "store": r.store, "link_type": "direct"},
        item_payloads=[],
    )
    original_no = r.sample.fulfillment_no
    for link_type in ("YYJL", "direct"):
        assert patch_sample(r, {"link_type": link_type}).status_code == 200
        r.sample.refresh_from_db()
        assert r.sample.link_type == link_type
        assert r.sample.fulfillment_no == original_no
        assert r.sample.outreach_task_id is None
        r.sample.full_clean()


def test_sample_type_stale_invalid_forbidden_and_cross_tenant_edits(records):
    r = records
    assert patch_sample(r, {"link_type": "invalid"}).status_code == 400
    assert patch_sample(r, {"link_type": "YYJL"}, version=r.sample.version - 1).status_code == 409
    _, viewer = user_with_permissions(r.tenant, "sample-type-viewer", "influencers.fulfillment.view")
    url = f"/api/internal/influencers/sample-fulfillments/{r.sample.pk}/"
    assert viewer.patch(url, {"link_type": "YYJL"}, format="json", HTTP_IF_MATCH='"1"').status_code == 403
    foreign = Tenant.objects.create(name="Foreign sample type", code="foreign-sample-type")
    _, foreign_client = user_with_permissions(foreign, "foreign-sample-type", "influencers.fulfillment.manage")
    assert foreign_client.patch(url, {"link_type": "YYJL"}, format="json", HTTP_IF_MATCH='"1"').status_code == 404
    r.sample.refresh_from_db()
    assert r.sample.link_type == "DRJL"
