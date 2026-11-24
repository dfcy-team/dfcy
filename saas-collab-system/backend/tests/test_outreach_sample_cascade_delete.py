import pytest

from apps.audit.models import OperationLog
from apps.influencers import services
from apps.influencers.models import SampleFulfillment
from tests.test_influencer_editable_fields import records
from tests.test_influencer_fulfillment import user_with_permissions

pytestmark = pytest.mark.django_db


def add_sample(r, key, task=None, link_type=None):
    payload = {'influencer': r.influencer, 'store': r.store}
    if task is not None:
        payload['outreach_task'] = task
    if link_type:
        payload['link_type'] = link_type
    sample, _ = services.create_sample_fulfillment(user=r.user, request_key=key,
                                                  validated_data=payload, item_payloads=[])
    return sample


def delete_task(r, version=None):
    r.task.refresh_from_db()
    return r.client.delete(f'/api/internal/influencers/outreach-tasks/{r.task.pk}/',
                           HTTP_IF_MATCH=f'"{r.task.version if version is None else version}"')


def test_task_delete_cascades_active_samples_only_and_keeps_history(records):
    r = records
    active = add_sample(r, 'cascade-active', r.task)
    previously_deleted = add_sample(r, 'cascade-previously-deleted', r.task)
    services.soft_delete_sample_fulfillment(user=r.user, fulfillment=previously_deleted,
                                           expected_version=previously_deleted.version)
    previously_deleted.refresh_from_db()
    old_version, old_time = previously_deleted.version, previously_deleted.deleted_at
    standalone = add_sample(r, 'cascade-standalone', link_type='direct')
    before = SampleFulfillment.objects.count()
    response = delete_task(r)
    assert response.status_code == 200, response.data
    assert response.data['data']['deleted_sample_count'] == 2
    r.task.refresh_from_db()
    assert r.task.is_deleted
    for sample in [r.sample, active]:
        sample.refresh_from_db()
        assert sample.is_deleted and sample.deleted_by_id == r.user.pk
        assert OperationLog.objects.filter(action='sample_delete', object_id=str(sample.pk)).exists()
    previously_deleted.refresh_from_db()
    assert (previously_deleted.version, previously_deleted.deleted_at) == (old_version, old_time)
    standalone.refresh_from_db()
    assert not standalone.is_deleted
    assert SampleFulfillment.objects.count() == before
    audit = OperationLog.objects.get(action='outreach_delete', object_id=str(r.task.pk))
    assert set(audit.after_data['deleted_sample_ids']) == {r.sample.pk, active.pk}
    services.restore_outreach_task(user=r.user, task=r.task, expected_version=r.task.version, recompute_related=False)
    assert SampleFulfillment.objects.get(pk=r.sample.pk).is_deleted


def test_missing_fulfillment_permission_refuses_entire_delete(records):
    r = records
    user, client = user_with_permissions(r.tenant, 'cascade-no-sample-permission', 'influencers.outreach.manage')
    r.task.refresh_from_db()
    response = client.delete(f'/api/internal/influencers/outreach-tasks/{r.task.pk}/', HTTP_IF_MATCH=f'"{r.task.version}"')
    assert response.status_code == 403
    r.task.refresh_from_db()
    r.sample.refresh_from_db()
    assert not r.task.is_deleted and not r.sample.is_deleted


def test_hidden_sample_refuses_entire_delete(records, monkeypatch):
    r = records
    from apps.influencers import scopes
    original = scopes.filter_queryset
    def restricted(actor, queryset, code, *args, **kwargs):
        if code == 'influencers.fulfillment.manage' and queryset.model is SampleFulfillment:
            return queryset.none()
        return original(actor, queryset, code, *args, **kwargs)
    monkeypatch.setattr(scopes, 'filter_queryset', restricted)
    assert delete_task(r).status_code == 403
    r.task.refresh_from_db()
    r.sample.refresh_from_db()
    assert not r.task.is_deleted and not r.sample.is_deleted


def test_stale_task_version_deletes_nothing(records):
    r = records
    response = delete_task(r, version=0)
    assert response.status_code == 409
    r.sample.refresh_from_db()
    assert not r.sample.is_deleted


def test_audit_failure_rolls_back_parent_children_and_child_audits(records, monkeypatch):
    r = records
    original = services._audit
    def fail_parent(*args, **kwargs):
        if args[1] == 'outreach_delete':
            raise RuntimeError('synthetic audit failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(services, '_audit', fail_parent)
    r.task.refresh_from_db()
    with pytest.raises(RuntimeError, match='synthetic audit failure'):
        services.soft_delete_outreach_task(user=r.user, task=r.task, expected_version=r.task.version)
    r.task.refresh_from_db()
    r.sample.refresh_from_db()
    assert not r.task.is_deleted and not r.sample.is_deleted
    assert not OperationLog.objects.filter(action='sample_delete', object_id=str(r.sample.pk)).exists()


def test_import_reconciliation_can_preserve_source_manifest_samples(records):
    r = records
    r.task.refresh_from_db()
    services.soft_delete_outreach_task(user=r.user, task=r.task, expected_version=r.task.version, cascade_samples=False)
    r.sample.refresh_from_db()
    assert not r.sample.is_deleted


def test_cross_tenant_delete_cannot_reach_task_or_children(records):
    r = records
    from apps.tenants.models import Tenant
    foreign = Tenant.objects.create(name='Foreign cascade', code='foreign-cascade')
    _, client = user_with_permissions(foreign, 'foreign-cascade', 'influencers.outreach.manage', 'influencers.fulfillment.manage')
    response = client.delete(f'/api/internal/influencers/outreach-tasks/{r.task.pk}/', HTTP_IF_MATCH=f'"{r.task.version}"')
    assert response.status_code == 404
    r.task.refresh_from_db()
    r.sample.refresh_from_db()
    assert not r.task.is_deleted and not r.sample.is_deleted


def test_task_without_samples_does_not_require_fulfillment_permission(records):
    r = records
    task = services.create_outreach_task(user=r.user, validated_data={
        'task_name': 'Empty task', 'store': r.store, 'owner': r.user,
        'external_product_id': r.task.external_product_id,
    })
    _, client = user_with_permissions(r.tenant, 'cascade-empty-task', 'influencers.outreach.manage')
    response = client.delete(f'/api/internal/influencers/outreach-tasks/{task.pk}/', HTTP_IF_MATCH=f'"{task.version}"')
    assert response.status_code == 200, response.data
    assert response.data['data']['deleted_sample_count'] == 0
