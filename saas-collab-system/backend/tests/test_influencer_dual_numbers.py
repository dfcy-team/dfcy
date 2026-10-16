from io import StringIO
import json

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command, CommandError
from django.db.models import QuerySet

from apps.audit.models import OperationLog
from apps.influencers.business_numbers import next_number, reserved_owner
from apps.influencers.management.commands.backfill_sample_business_numbers import make_plan
from apps.influencers.models import InfluencerNumberReservation, SampleFulfillment, BdSampleAttributionSnapshot
from apps.influencers.services import create_sample_fulfillment, soft_delete_sample_fulfillment
from tests.test_influencer_editable_fields import records, patch_sample, patch_task
from tests.test_influencer_fulfillment import user_with_permissions
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def raw_sample(r, number, kind="YYJL"):
    return SampleFulfillment.objects.create(
        tenant=r.tenant, fulfillment_no=number, request_key="legacy-" + number, request_hash="a" * 64,
        influencer=r.influencer, store=r.store, owner=r.user, link_type=kind,
    )


def test_global_YPDD_and_independent_type_numbers(records):
    r = records
    raw_sample(r, "YPDD10987")
    samples = []
    for kind in ("YYJL", "PKDJ", "ZBDR", "TKOne", "YYJL"):
        sample, _ = create_sample_fulfillment(user=r.user, request_key="new-" + str(len(samples)),
            validated_data={"influencer": r.influencer, "store": r.store, "external_product_id": "EXAMPLE", "link_type": kind}, item_payloads=[])
        samples.append(sample)
    assert [s.fulfillment_no for s in samples] == [f"YPDD{n}" for n in range(10988, 10993)]
    assert [s.type_no for s in samples] == ["YYJL0001", "PKDJ0001", "ZBDR0001", "TKOne0001", "YYJL0002"]


def test_sample_number_only_edit_does_not_reprice_ship_or_change_relations(records):
    r = records
    QuerySet.update(SampleFulfillment.objects.filter(pk=r.sample.pk), sample_order_no="EXAMPLE-ORDER")
    before = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    snapshot = list(BdSampleAttributionSnapshot.objects.filter(fulfillment=r.sample).values())
    assert patch_sample(r, {"fulfillment_no": " YPDD10646 "}).status_code == 200
    after = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    for key in before.keys() - {"fulfillment_no", "version", "updated_at"}:
        assert after[key] == before[key]
    assert after["fulfillment_no"] == "YPDD10646"
    assert list(BdSampleAttributionSnapshot.objects.filter(fulfillment=r.sample).values()) == snapshot
    assert reserved_owner(r.tenant.pk, "sample", before["fulfillment_no"]).pk == r.sample.pk
    audit = OperationLog.objects.get(action="sample_update", object_id=str(r.sample.pk))
    assert audit.before_data["fulfillment_no"] == before["fulfillment_no"]
    assert audit.after_data["fulfillment_no"] == "YPDD10646"


@pytest.mark.parametrize("field", ["fulfillment_no", "type_no"])
@pytest.mark.parametrize("value", [None, "", " ", "A" * 81])
def test_invalid_identifiers_rejected(records, field, value):
    r = records
    before = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    assert patch_sample(r, {field: value}).status_code == 400
    assert SampleFulfillment.objects.values().get(pk=r.sample.pk) == before


def test_identifier_only_edit_never_calls_current_cost_refresh(records, monkeypatch):
    def unexpected_refresh(**kwargs):
        raise AssertionError("Identifier-only edits must not refresh confirmed costs")

    monkeypatch.setattr("apps.influencers.services._refresh_existing_sample_costs", unexpected_refresh)
    assert patch_sample(records, {"type_no": "DRJL0999"}).status_code == 200


@pytest.mark.parametrize("field", ["fulfillment_no", "type_no"])
def test_old_and_deleted_identifiers_remain_reserved(records, field):
    r = records
    old = getattr(r.sample, field)
    assert patch_sample(r, {field: "YPDD99999" if field == "fulfillment_no" else "DRJL9999"}).status_code == 200
    other = raw_sample(r, "YPDD88888")
    r.sample = other
    before = SampleFulfillment.objects.values().get(pk=other.pk)
    assert patch_sample(r, {field: old}).status_code == 409
    assert SampleFulfillment.objects.values().get(pk=other.pk) == before
    assert patch_sample(r, {field: old.lower()}).status_code == 409


def test_renamed_highest_number_is_not_reallocated(records):
    r = records
    assert patch_sample(r, {"fulfillment_no": "YPDD99999"}).status_code == 200
    r.sample.refresh_from_db()
    assert patch_sample(r, {"fulfillment_no": "YPDD10646"}).status_code == 200
    assert next_number(r.tenant, "sample", "YPDD", width=5) == "YPDD100000"


def test_type_edit_leaves_YPDD_and_task_unchanged(records):
    r = records
    old_no, old_task, old_type = r.sample.fulfillment_no, r.sample.outreach_task_id, r.sample.type_no
    response = patch_sample(r, {"link_type": "YYJL"})
    assert response.status_code == 200
    assert response.data["data"]["fulfillment_no"] == old_no
    assert response.data["data"]["outreach_task"] == old_task
    assert response.data["data"]["type_no"] == "YYJL0001"
    assert reserved_owner(r.tenant.pk, "type", old_type).pk == r.sample.pk


def test_task_renaming_updates_all_related_sample_reads_and_search(records):
    r = records
    second, _ = create_sample_fulfillment(user=r.user, request_key="another-example", validated_data={
        "outreach_task": r.task, "influencer": r.influencer, "store": r.store,
    }, item_payloads=[])
    r.task.refresh_from_db()
    old_numbers = list(SampleFulfillment.objects.values_list("id", "fulfillment_no", "type_no"))
    assert patch_task(r, {"task_no": "DRJL0280"}).status_code == 200
    for sample in (r.sample, second):
        response = r.client.get(f"/api/internal/influencers/sample-fulfillments/{sample.pk}/")
        assert response.data["data"]["outreach_task_no"] == "DRJL0280"
        assert response.data["data"]["outreach_task"] == r.task.pk
    response = r.client.get("/api/internal/influencers/sample-fulfillments/", {"search": "DRJL0280"})
    assert response.data["data"]["count"] == 2
    assert list(SampleFulfillment.objects.values_list("id", "fulfillment_no", "type_no")) == old_numbers


def test_type_number_search_and_permission_isolation(records):
    r = records
    assert r.client.get("/api/internal/influencers/sample-fulfillments/", {"search": r.sample.type_no}).data["data"]["count"] == 1
    user, client = user_with_permissions(r.tenant, "number-reader", "influencers.fulfillment.view")
    assert client.patch(f"/api/internal/influencers/sample-fulfillments/{r.sample.pk}/", {"fulfillment_no": "DENIED"}, format="json", HTTP_IF_MATCH='"1"').status_code == 403
    other = Tenant.objects.create(name="Unrelated", code="unrelated-numbering")
    user, client = user_with_permissions(other, "other-number-manager", "influencers.fulfillment.manage")
    assert client.patch(f"/api/internal/influencers/sample-fulfillments/{r.sample.pk}/", {"fulfillment_no": "DENIED"}, format="json", HTTP_IF_MATCH='"1"').status_code == 404
    with pytest.raises(DjangoValidationError):
        InfluencerNumberReservation.objects.create(tenant=other, namespace="sample", number="WRONG-TENANT", sample=r.sample)


def test_number_edit_version_and_audit_failure_are_atomic(records, monkeypatch):
    r = records
    before = SampleFulfillment.objects.values().get(pk=r.sample.pk)
    aliases = list(InfluencerNumberReservation.objects.values())
    assert patch_sample(r, {"fulfillment_no": "STALE"}, version=0).status_code == 409
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit fault")
    monkeypatch.setattr("apps.influencers.services._audit", fail)
    with pytest.raises(RuntimeError, match="Synthetic"):
        patch_sample(r, {"fulfillment_no": "ROLLBACK"})
    assert SampleFulfillment.objects.values().get(pk=r.sample.pk) == before
    assert list(InfluencerNumberReservation.objects.values()) == aliases


def preview(r, path):
    call_command("backfill_sample_business_numbers", tenant_id=r.tenant.pk, actor_id=r.user.pk,
                 report_path=str(path), stdout=StringIO())
    return json.loads(path.read_text())


def test_backfill_preserves_YPDD_and_manual_type_numbers_then_is_zero_write(records, tmp_path):
    r = records
    history = raw_sample(r, "YPDD10987", "YYJL")
    manual = raw_sample(r, "YYJL0007", "YYJL")
    before_relations = list(SampleFulfillment.objects.values_list("id", "influencer_id", "outreach_task_id", "owner_id"))
    plan_path = tmp_path / "preview.json"
    plan = preview(r, plan_path)
    assert plan["summary"]["YPDD_renames"] == 1
    call_command("backfill_sample_business_numbers", tenant_id=r.tenant.pk, actor_id=r.user.pk,
                 apply=True, expected_plan=str(plan_path), report_path=str(tmp_path / "applied.json"), stdout=StringIO())
    history.refresh_from_db()
    manual.refresh_from_db()
    assert history.fulfillment_no == "YPDD10987"
    assert history.type_no == "YYJL0008"
    assert manual.fulfillment_no == "YPDD10988" and manual.type_no == "YYJL0007"
    assert list(SampleFulfillment.objects.values_list("id", "influencer_id", "outreach_task_id", "owner_id")) == before_relations
    assert reserved_owner(r.tenant.pk, "sample", "YYJL0007").pk == manual.pk
    again = make_plan(r.tenant)
    assert again["changes"] == [] and again["reservations"] == []


def test_report_failure_rolls_back_all_number_and_alias_writes(records, tmp_path, monkeypatch):
    r = records
    raw_sample(r, "YYJL0007")
    plan_path = tmp_path / "preview.json"
    preview(r, plan_path)
    before = list(SampleFulfillment.objects.values())
    aliases = list(InfluencerNumberReservation.objects.values())
    def fail(*args):
        raise OSError("Synthetic fsync fault")
    monkeypatch.setattr("apps.influencers.management.commands.backfill_sample_business_numbers.os.fsync", fail)
    with pytest.raises(CommandError, match="rolled back"):
        call_command("backfill_sample_business_numbers", tenant_id=r.tenant.pk, actor_id=r.user.pk,
                     apply=True, expected_plan=str(plan_path), report_path=str(tmp_path / "failed.json"), stdout=StringIO())
    assert list(SampleFulfillment.objects.values()) == before
    assert list(InfluencerNumberReservation.objects.values()) == aliases
    assert not OperationLog.objects.filter(action="backfill_sample_business_numbers").exists()


def test_stale_plan_or_existing_report_never_writes(records, tmp_path):
    r = records
    raw_sample(r, "YYJL0007")
    plan_path = tmp_path / "preview.json"
    preview(r, plan_path)
    before = list(SampleFulfillment.objects.values())
    with pytest.raises(CommandError, match="Cannot create"):
        call_command("backfill_sample_business_numbers", tenant_id=r.tenant.pk, actor_id=r.user.pk,
                     apply=True, expected_plan=str(plan_path), report_path=str(plan_path), stdout=StringIO())
    assert list(SampleFulfillment.objects.values()) == before
    raw_sample(r, "YPDD10999")
    before = list(SampleFulfillment.objects.values())
    with pytest.raises(CommandError, match="changed since"):
        call_command("backfill_sample_business_numbers", tenant_id=r.tenant.pk, actor_id=r.user.pk,
                     apply=True, expected_plan=str(plan_path), report_path=str(tmp_path / "stale.json"), stdout=StringIO())
    assert list(SampleFulfillment.objects.values()) == before
