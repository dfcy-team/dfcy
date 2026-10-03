from django.db import transaction

from .models import SavedReportView, SavedReportViewRevision


def _snapshot(view, actor, action):
    SavedReportViewRevision.objects.create(
        view=view, version=view.version, config=view.config, name=view.name,
        is_shared=view.is_shared, action=action, actor=actor,
    )


@transaction.atomic
def create_view(*, tenant, owner, actor, **values):
    view = SavedReportView.objects.create(tenant=tenant, owner=owner, **values)
    _snapshot(view, actor, SavedReportViewRevision.Action.CREATE)
    return view


@transaction.atomic
def update_view(view_id, actor, values, expected_version=None):
    view = SavedReportView.objects.select_for_update().get(
        pk=view_id, tenant_id=actor.tenant_id, owner=actor, is_archived=False
    )
    if expected_version is not None and view.version != expected_version:
        raise ValueError("报表视图已更新，请刷新后重试。")
    for key, value in values.items():
        setattr(view, key, value)
    view.version += 1
    view.full_clean()
    view.save()
    _snapshot(view, actor, SavedReportViewRevision.Action.UPDATE)
    return view


@transaction.atomic
def archive_view(view, actor):
    view = SavedReportView.objects.select_for_update().get(
        pk=view.pk, tenant_id=actor.tenant_id, owner=actor, is_archived=False
    )
    view.version += 1
    view.is_archived = True
    view.save(update_fields=["version", "is_archived", "updated_at"])
    _snapshot(view, actor, SavedReportViewRevision.Action.ARCHIVE)
    return view
