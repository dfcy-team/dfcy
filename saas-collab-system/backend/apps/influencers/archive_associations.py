"""Explicit associations of independently owned full archives, without identity fanout."""

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.tenants.models import Tenant

from .models import (
    InfluenceArchiveGroup, InfluenceArchiveMembership, Influencer,
    InfluencerPlatformAccount, influencer_has_active_restriction,
)
from .platform_accounts import (
    InfluencerFormConflict, get_influencer_form, require_influencer_form_access,
    require_influencer_nickname_access, save_influencer_aggregate,
)
from .serializers import (
    InfluencerArchiveSummarySerializer, InfluencerContactSerializer,
    InfluencerProfileSerializer, InfluencerSerializer,
)


def archive_group_data(influencer):
    """Called only after a purpose guard, inside the tenant-locked read/write transaction."""
    membership = InfluenceArchiveMembership.objects.filter(
        tenant_id=influencer.tenant_id, influencer_id=influencer.pk,
        group__tenant_id=influencer.tenant_id,
    ).select_related("group").first()
    member_ids = InfluenceArchiveMembership.objects.filter(
        tenant_id=influencer.tenant_id, group_id=membership.group_id,
    ).values("influencer_id") if membership else []
    rows = Influencer.objects.filter(tenant_id=influencer.tenant_id).filter(
        Q(pk=influencer.pk) | Q(pk__in=member_ids),
    ).select_related("profile").order_by("id")
    return {
        "archive_group_id": membership.group_id if membership else None,
        "group_version": membership.group.version if membership else None,
        "related_archives": list(InfluencerArchiveSummarySerializer(rows, many=True).data),
    }


@transaction.atomic
def get_related_archives(*, user, influencer_id, for_form=False):
    if for_form:
        require_influencer_form_access(user)
    else:
        require_influencer_nickname_access(user)
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    influencer = get_object_or_404(Influencer.objects, tenant_id=user.tenant_id, pk=influencer_id)
    return archive_group_data(influencer)


def _source_version(value):
    if isinstance(value, str):
        try:
            value = parse_datetime(value.strip().strip('"'))
        except ValueError:
            value = None
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValidationError({"If-Match": "The current timezone-aware updated_at timestamp is required."})
    return value


def _writable_fields(serializer):
    return {name for name, field in serializer.fields.items() if not field.read_only}


def _validate_archive(archive):
    if not isinstance(archive, dict):
        raise ValidationError({"archive": "Expected a new full archive object."})
    allowed = _writable_fields(InfluencerSerializer()) | {"contacts", "nickname_id", "account_nickname"}
    unknown = set(archive) - allowed
    if unknown:
        raise ValidationError({"archive": {key: "Unknown or server-owned field." for key in sorted(unknown)}})
    platform = archive.get("platform")
    if not isinstance(platform, str) or platform.strip().lower() not in InfluencerPlatformAccount.Platform.values:
        raise ValidationError({"archive": {"platform": "A supported primary platform is required."}})
    for section, serializer in (("profile", InfluencerProfileSerializer()), ("contacts", InfluencerContactSerializer())):
        if section not in archive:
            continue
        values = [archive[section]] if section == "profile" else archive[section]
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            raise ValidationError({"archive": {section: "Expected profile object or contact objects."}})
        allowed = _writable_fields(serializer)
        if any(set(value) - allowed for value in values):
            raise ValidationError({"archive": {section: "Unknown or server-owned nested fields are not allowed."}})
    return {**archive, "platform": platform.strip().lower()}


def _advance_member_versions(members, updated_at):
    # Do not use Influencer.save(): timestamps must not invoke TikTok identity fanout.
    for member in members:
        changed = QuerySet.update(
            Influencer.objects.filter(tenant_id=member.tenant_id, pk=member.pk, updated_at=member.updated_at),
            updated_at=updated_at,
        )
        if changed != 1:
            raise InfluencerFormConflict()
        member.updated_at = updated_at


@transaction.atomic
def create_related_archive(*, user, source_id, archive, expected_updated_at):
    require_influencer_form_access(user)
    archive = _validate_archive(archive)
    expected_updated_at = _source_version(expected_updated_at)
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    membership = InfluenceArchiveMembership.objects.filter(
        tenant_id=user.tenant_id, influencer_id=source_id, group__tenant_id=user.tenant_id,
    ).first()
    member_ids = set(InfluenceArchiveMembership.objects.filter(
        tenant_id=user.tenant_id, group_id=membership.group_id,
    ).values_list("influencer_id", flat=True)) if membership else set()
    member_ids.add(source_id)
    members = list(Influencer.objects.select_for_update().filter(
        tenant_id=user.tenant_id, pk__in=sorted(member_ids),
    ).order_by("pk"))
    source = next((member for member in members if member.pk == source_id), None)
    if source is None:
        source = get_object_or_404(Influencer.objects, tenant_id=user.tenant_id, pk=source_id)
    group = get_object_or_404(
        InfluenceArchiveGroup.objects.select_for_update(), tenant_id=user.tenant_id, pk=membership.group_id,
    ) if membership else None
    if source.updated_at != expected_updated_at:
        raise InfluencerFormConflict({"If-Match": "Source archive was changed by another request."})
    if influencer_has_active_restriction(source):
        raise ValidationError({"archive": "A restricted source cannot create a related archive."})
    created = save_influencer_aggregate(user=user, payload=archive)
    old_version = group.version if group else None
    existing_ids = sorted(member.pk for member in members)
    if group is None:
        group = InfluenceArchiveGroup.objects.create(tenant=user.tenant, created_by=user, updated_by=user)
        InfluenceArchiveMembership.objects.create(tenant=user.tenant, group=group, influencer=source, created_by=user)
    InfluenceArchiveMembership.objects.create(tenant=user.tenant, group=group, influencer=created, created_by=user)
    members.append(created)
    updated_at = max(timezone.now(), *(member.updated_at + timedelta(microseconds=1) for member in members), group.updated_at + timedelta(microseconds=1))
    _advance_member_versions(sorted(members, key=lambda member: member.pk), updated_at)
    if old_version is not None:
        changed = QuerySet.update(
            InfluenceArchiveGroup.objects.filter(tenant_id=user.tenant_id, pk=group.pk, version=old_version, updated_at=group.updated_at),
            version=old_version + 1, updated_by_id=user.pk, updated_at=updated_at,
        )
        if changed != 1:
            raise InfluencerFormConflict()
        group.version = old_version + 1
    write_operation_log(
        tenant=user.tenant, user=user, module="influencers", action="related_archive_create",
        object_type="influencer_archive_group", object_id=group.pk,
        before_data={"member_ids": existing_ids, "group_version": old_version},
        after_data={
            "source_id": source.pk, "archive_id": created.pk, "archive_group_id": group.pk,
            "member_ids": sorted(member.pk for member in members), "group_version": group.version, "outcome": "created",
        },
    )
    return get_influencer_form(user=user, influencer_id=created.pk)
