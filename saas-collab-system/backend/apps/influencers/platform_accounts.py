"""Manual phase-1 account aggregates; never merge identities or fetch platforms."""

import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q, QuerySet
from django.db.models.functions import Lower, Trim
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.tenants.models import Tenant

from .models import (
    Influencer, InfluencerContact, InfluencerPlatformAccount, InfluencerProfile,
    influencer_has_active_restriction, normalize_tiktok_username,
)
from .serializers import (
    InfluencerContactSerializer, InfluencerPlatformAccountSerializer,
    InfluencerProfileSerializer, InfluencerSerializer,
)


ACCOUNT_FIELDS = (
    "handle", "external_account_id", "display_name", "profile_url", "follower_count", "is_active",
)
SECTIONS = {"profile", "contacts", "platform_accounts"}


class InfluencerFormConflict(APIException):
    status_code = 409
    default_detail = "Influencer was changed by another request."
    default_code = "conflict"


def require_influencer_form_access(user):
    if not (
        user and user.is_authenticated and user.is_active and user.tenant_id
        and user.user_type == CustomUser.UserType.INTERNAL
        and check_user_permission(user, "influencers.manage")
    ):
        raise PermissionDenied("Influencer forms require influencers.manage.")
    require_all_scope(user, "influencers.manage")


def require_influencer_nickname_access(user):
    if not (
        user and user.is_authenticated and user.is_active and user.tenant_id
        and user.user_type == CustomUser.UserType.INTERNAL
        and check_user_permission(user, "influencers.view")
    ):
        raise PermissionDenied("Nickname identifiers require internal influencers.view access.")
    require_all_scope(user, "influencers.view")


def map_identity_alias(data, alias, field, *, normalize=None, max_length):
    if alias not in data:
        return
    value = data.pop(alias)
    if not isinstance(value, str) or len(value) > max_length:
        raise ValidationError({alias: f"Expected a string of at most {max_length} characters."})
    normalize = normalize or (lambda item: item.strip())
    value = normalize(value)
    if field in data and (not isinstance(data[field], str) or normalize(data[field]) != value):
        raise ValidationError({alias: f"Conflicts with {field}."})
    data[field] = value


def _identity_alias_payload(payload, *, creating):
    payload = dict(payload)
    map_identity_alias(payload, "nickname_id", "handle", normalize=normalize_tiktok_username, max_length=255)
    if "account_nickname" in payload:
        profile = dict(payload.get("profile", {}))
        nickname = {"account_nickname": payload.pop("account_nickname")}
        if "display_name" in profile:
            nickname["display_name"] = profile["display_name"]
        map_identity_alias(nickname, "account_nickname", "display_name", max_length=160)
        profile["display_name"] = nickname["display_name"]
        payload["profile"] = profile
    if creating and "name" not in payload:
        name = (payload.get("profile") or {}).get("display_name") or payload.get("handle", "")
        # Legacy consumers need a bounded name; the complete nickname stays in the profile.
        payload["name"] = name[:Influencer._meta.get_field("name").max_length] if isinstance(name, str) else name
    return payload


def platform_account_prefetch(tenant_id, *, active_only=False, summaries_only=False):
    rows = InfluencerPlatformAccount.objects.filter(tenant_id=tenant_id)
    if active_only:
        rows = rows.filter(is_active=True)
    if summaries_only:
        rows = rows.only("id", "tenant_id", "influencer_id", "platform", "is_active")
    return Prefetch("platform_accounts", queryset=rows, to_attr="_platform_account_rows")


def _form_queryset(user):
    return Influencer.objects.filter(tenant_id=user.tenant_id).select_related("profile").prefetch_related(
        platform_account_prefetch(user.tenant_id),
        Prefetch("contacts", queryset=InfluencerContact.objects.filter(tenant_id=user.tenant_id, is_active=True).order_by("-is_primary", "id"), to_attr="_form_contacts"),
        "restrict_events__actor",
    )


@transaction.atomic
def get_influencer_form(*, user, influencer_id):
    require_influencer_form_access(user)
    from .archive_associations import archive_group_data

    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    influencer = get_object_or_404(_form_queryset(user), pk=influencer_id)
    influencer._archive_group_data = archive_group_data(influencer)
    return influencer


def legacy_primary_account_values(influencer):
    profile = getattr(influencer, "profile", None)
    if profile is not None and profile.tenant_id != influencer.tenant_id:
        profile = None
    return {
        "platform": str(influencer.platform or "").strip().lower(),
        "handle": normalize_tiktok_username(influencer.handle),
        "external_account_id": str(getattr(profile, "external_influencer_id", "") or "").strip(),
        "display_name": getattr(profile, "display_name", ""),
        "profile_url": getattr(profile, "profile_url", "") or "",
        "follower_count": influencer.follower_count or None,
        "is_active": True,
    }


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def assert_account_identity_available(*, tenant_id, influencer_id, platform, values):
    if not values["is_active"]:
        return
    handle = normalize_tiktok_username(values["handle"])
    external_id = values["external_account_id"]
    if not (handle or external_id):
        return
    match = Q(pk__in=[])
    if handle:
        match |= Q(active_handle_digest=_digest(handle))
    if external_id:
        match |= Q(active_external_id_digest=_digest(external_id))
    if InfluencerPlatformAccount.objects.filter(tenant_id=tenant_id, platform=platform).exclude(influencer_id=influencer_id).filter(match).exists():
        raise ValidationError({"platform_accounts": "An active account already reserves this identity."})
    # NULL denotes an unindexed legacy row, including rows with empty identity.
    # Claims stay closed until all writers are upgraded and the bounded backfill finishes.
    if Influencer.objects.filter(tenant_id=tenant_id, canonical_handle_digest__isnull=True).exists() or InfluencerProfile.objects.filter(
        tenant_id=tenant_id, canonical_external_id_digest__isnull=True,
    ).exists():
        raise ValidationError({"platform_accounts": "Legacy identity indexes are not ready; retry after backfill."})
    parents = Influencer.objects.filter(tenant_id=tenant_id).exclude(pk=influencer_id)
    handle_claimed = handle and parents.filter(canonical_handle_digest=_digest(handle)).annotate(
        _legacy_platform=Lower(Trim("platform")),
    ).filter(_legacy_platform=platform).exists()
    external_claimed = external_id and InfluencerProfile.objects.filter(
        tenant_id=tenant_id, influencer__tenant_id=tenant_id, canonical_external_id_digest=_digest(external_id),
    ).exclude(influencer_id=influencer_id).annotate(
        _legacy_platform=Lower(Trim("influencer__platform")),
    ).filter(_legacy_platform=platform).exists()
    if handle_claimed or external_claimed:
        raise ValidationError({"platform_accounts": "A legacy primary account already reserves this identity."})


def _save_validated(row, *, update_fields=None):
    try:
        row.save(**({"update_fields": update_fields} if update_fields is not None else {}))
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
    except IntegrityError as exc:
        raise ValidationError("The account or contact identity conflicts with an existing record.") from exc


def _validate_sections(payload):
    if not isinstance(payload, dict):
        raise ValidationError("Expected an influencer object.")
    for field in SECTIONS.intersection(payload):
        expected_type = dict if field == "profile" else list
        if not isinstance(payload[field], expected_type):
            raise ValidationError({field: "Expected an object." if field == "profile" else "Expected an array."})
    if len(payload.get("platform_accounts", [])) > 4:
        raise ValidationError({"platform_accounts": "At most four unique platforms are allowed."})
    if len(payload.get("contacts", [])) > 100:
        raise ValidationError({"contacts": "At most 100 contacts are allowed."})


def _account_payloads(payload):
    result = {}
    for item in payload.get("platform_accounts", []):
        if not isinstance(item, dict):
            raise ValidationError({"platform_accounts": "Each account must be an object."})
        serializer = InfluencerPlatformAccountSerializer(data=item, partial=True)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        platform = values.pop("platform", None)
        if platform is None or platform in result:
            raise ValidationError({"platform_accounts": "Each entry needs a unique platform."})
        result[platform] = (values, item)
    return result


def _contact_plans(payload, existing):
    if "contacts" not in payload:
        return []
    supplied = {}
    for item in payload["contacts"]:
        if not isinstance(item, dict):
            raise ValidationError({"contacts": "Each contact must be an object."})
        serializer = InfluencerContactSerializer(data=item)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        key = (values["channel"], values["value"])
        if key in supplied:
            raise ValidationError({"contacts": "Duplicate contacts are not allowed."})
        supplied[key] = {
            "channel": key[0], "value": key[1], "label": values.get("label", ""),
            "is_primary": values.get("is_primary", False) and values.get("is_active", True), "is_active": values.get("is_active", True),
        }
    if sum(values["is_active"] and values["is_primary"] for values in supplied.values()) > 1:
        raise ValidationError({"contacts": "Only one active primary contact is allowed."})
    plans = []
    for key in existing.keys() | supplied.keys():
        row = existing.get(key)
        values = supplied.get(key)
        if values is None:
            values = {"is_active": False, "is_primary": False}
        if row is None or any(getattr(row, field) != value for field, value in values.items()):
            plans.append((row, values))
    # Release the old primary first so a replacement can be validated normally.
    return sorted(plans, key=lambda plan: bool(plan[1].get("is_primary", False)))


def _account_plans(influencer, supplied, existing, profile_data):
    legacy = legacy_primary_account_values(influencer)
    primary = legacy["platform"]
    if "display_name" in profile_data and (primary in existing or primary in supplied):
        changes, raw = supplied.get(primary, ({}, {}))
        if "display_name" in changes and changes["display_name"] != profile_data["display_name"]:
            raise ValidationError({"account_nickname": "Primary account nickname must match the profile."})
        supplied[primary] = ({**changes, "display_name": profile_data["display_name"]}, raw)
    old_external = legacy["external_account_id"]
    new_external = str(profile_data.get("external_influencer_id", old_external) or "").strip()
    if old_external and new_external != old_external:
        raise ValidationError({"profile": "The populated primary external ID cannot change."})
    primary_values = supplied.get(primary, ({}, {}))[0]
    if "external_account_id" in primary_values:
        requested = primary_values["external_account_id"]
        if requested != new_external:
            if not old_external and not new_external:
                new_external = requested
            elif not (not old_external and not requested and new_external):
                raise ValidationError({"platform_accounts": "Primary external ID must match the legacy profile."})
    if new_external != old_external:
        profile_data["external_influencer_id"] = new_external
        if primary in existing and primary not in supplied:
            supplied[primary] = ({"external_account_id": new_external}, {})
    plans = []
    for platform, (changes, raw) in supplied.items():
        row = existing.get(platform)
        is_primary = platform == primary
        if "is_primary" in raw and raw["is_primary"] is not is_primary:
            raise ValidationError({"platform_accounts": "Primary status is server-derived and cannot change."})
        if "id" in raw and raw["id"] != (row.pk if row else None):
            raise ValidationError({"platform_accounts": "Account ID does not match this parent/platform slot."})
        if is_primary:
            if changes.get("is_active", True) is not True or (
                "handle" in changes and changes["handle"] != legacy["handle"]
            ):
                raise ValidationError({"platform_accounts": "Primary handle and active status cannot change."})
            changes["external_account_id"] = new_external
        baseline = {field: getattr(row, field) for field in ACCOUNT_FIELDS} if row else (
            {field: legacy[field] for field in ACCOUNT_FIELDS} if is_primary else {
                "handle": "", "external_account_id": "", "display_name": "", "profile_url": "",
                "follower_count": None, "is_active": True,
            }
        )
        values = {**baseline, **changes}
        if row is None and is_primary and values == baseline:
            continue
        if row is not None and values == baseline:
            continue
        if values["is_active"] and not (values["handle"] or values["external_account_id"]):
            raise ValidationError({"platform_accounts": "An active account needs a handle or external account ID."})
        plans.append((platform, row, values))
    if (plans or new_external != old_external) and influencer_has_active_restriction(influencer):
        raise ValidationError({"platform_accounts": "Blacklisted influencer accounts cannot change."})
    if new_external != old_external and not any(platform == primary for platform, _, _ in plans):
        assert_account_identity_available(
            tenant_id=influencer.tenant_id, influencer_id=influencer.pk, platform=primary,
            values={**legacy, "external_account_id": new_external},
        )
    for platform, row, values in plans:
        if row is None or any(getattr(row, field) != values[field] for field in ("handle", "external_account_id", "is_active")):
            assert_account_identity_available(tenant_id=influencer.tenant_id, influencer_id=influencer.pk, platform=platform, values=values)
    return plans, old_external, new_external


def _generate_archive_code(tenant_id):
    for _ in range(5):
        code = f"DRDA-{uuid4().hex}"
        if not Influencer.objects.filter(tenant_id=tenant_id, code=code).exists():
            return code
    raise ValidationError({"code": "Unable to allocate an archive code. Please try again."})


@transaction.atomic
def save_influencer_aggregate(*, user, payload, influencer_id=None, expected_updated_at=None):
    require_influencer_form_access(user)
    _validate_sections(payload)
    payload = _identity_alias_payload(payload, creating=influencer_id is None)
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    creating = influencer_id is None
    influencer = None if creating else get_object_or_404(
        Influencer.objects.select_for_update(), tenant_id=user.tenant_id, pk=influencer_id,
    )
    if not creating:
        if isinstance(expected_updated_at, str):
            try:
                expected_updated_at = parse_datetime(expected_updated_at.strip().strip('"'))
            except ValueError:
                expected_updated_at = None
        if not isinstance(expected_updated_at, datetime) or timezone.is_naive(expected_updated_at):
            raise ValidationError({"If-Match": "The current timezone-aware updated_at timestamp is required."})
        if expected_updated_at != influencer.updated_at:
            raise InfluencerFormConflict({"If-Match": "Influencer was changed by another request."})
    parent_data = {key: value for key, value in payload.items() if key not in SECTIONS}
    # Keep imported codes compatible; interactive forms omit this server-generated identifier.
    if creating and ("code" not in parent_data or isinstance(parent_data["code"], str) and not parent_data["code"].strip()):
        parent_data["code"] = _generate_archive_code(user.tenant_id)
    if not creating:
        for field in ("platform", "handle"):
            if field not in parent_data:
                continue
            normalize = normalize_tiktok_username if field == "handle" else lambda value: str(value or "").strip().lower()
            if normalize(parent_data.pop(field)) != normalize(getattr(influencer, field)):
                raise ValidationError({field: "The aggregate form cannot change the primary identity."})
    serializer = InfluencerSerializer(influencer, data=parent_data, partial=not creating, context={"request": SimpleNamespace(user=user)})
    serializer.is_valid(raise_exception=True)
    if creating:
        if str(serializer.validated_data.get("platform", "")).strip().lower() not in InfluencerPlatformAccount.Platform.values:
            raise ValidationError({"platform": "Unsupported primary platform."})
        influencer = serializer.save(tenant=user.tenant)
    profile = InfluencerProfile.objects.select_for_update().filter(tenant_id=user.tenant_id, influencer=influencer).first()
    if profile is not None:
        influencer.profile = profile
    profile_data = {}
    if "profile" in payload:
        profile_serializer = InfluencerProfileSerializer(profile, data=payload["profile"], partial=True)
        profile_serializer.is_valid(raise_exception=True)
        profile_data = dict(profile_serializer.validated_data)
    contacts = {
        (row.channel, row.value): row for row in InfluencerContact.objects.select_for_update().filter(tenant_id=user.tenant_id, influencer=influencer).order_by("id")
    }
    accounts = {
        row.platform: row for row in InfluencerPlatformAccount.objects.select_for_update().filter(tenant_id=user.tenant_id, influencer=influencer).order_by("id")
    }
    contact_plans = _contact_plans(payload, contacts)
    account_plans, old_external, new_external = _account_plans(influencer, _account_payloads(payload), accounts, profile_data)
    if creating and not any(platform == str(influencer.platform).strip().lower() for platform, _, _ in account_plans):
        primary_values = {**legacy_primary_account_values(influencer), "external_account_id": new_external}
        assert_account_identity_available(tenant_id=user.tenant_id, influencer_id=influencer.pk, platform=primary_values["platform"], values=primary_values)
    before_accounts = [
        {"platform": platform, "handle_digest": _digest(row.handle), "external_id_digest": _digest(row.external_account_id)}
        for platform, row, _ in account_plans if row is not None
    ]
    parent_changes = {} if creating else {
        field: value for field, value in serializer.validated_data.items() if getattr(influencer, field) != value
    }
    if parent_changes:
        for field, value in parent_changes.items():
            setattr(influencer, field, value)
        _save_validated(influencer, update_fields=list(parent_changes))
    profile = profile or InfluencerProfile(tenant=user.tenant, influencer=influencer)
    profile_changes = {field: value for field, value in profile_data.items() if getattr(profile, field) != value}
    if profile_changes:
        for field, value in profile_changes.items():
            setattr(profile, field, value)
        _save_validated(profile)
        influencer.profile = profile
    for row, values in contact_plans:
        if row is None:
            row = InfluencerContact(tenant=user.tenant, influencer=influencer, created_by=user)
        for field, value in values.items():
            setattr(row, field, value)
        _save_validated(row)
    for platform, row, values in account_plans:
        if row is None:
            row = InfluencerPlatformAccount(tenant=user.tenant, influencer=influencer, platform=platform, created_by=user)
        else:
            row.influencer = influencer
        for field, value in values.items():
            setattr(row, field, value)
        row.updated_by = user
        _save_validated(row)
    changed = creating or bool(parent_changes or profile_changes or contact_plans or account_plans)
    if changed:
        if not creating:
            previous = influencer.updated_at
            advanced = max(timezone.now(), previous + timedelta(microseconds=1))
            if QuerySet.update(Influencer.objects.filter(tenant_id=user.tenant_id, pk=influencer.pk, updated_at=previous), updated_at=advanced) != 1:
                raise InfluencerFormConflict()
            influencer.updated_at = advanced
        write_operation_log(
            tenant=user.tenant, user=user, module="influencers",
            action="aggregate_create" if creating else "aggregate_update", object_type="influencer", object_id=influencer.pk,
            before_data={
                "external_id_digest": _digest(old_external),
                "accounts": before_accounts,
            },
            after_data={
                "parent_fields": sorted(parent_changes), "profile_fields": sorted(profile_changes),
                "contact_changes": len(contact_plans), "account_platforms": [platform for platform, _, _ in account_plans],
                "external_id_digest": _digest(new_external), "primary_external_id_filled": bool(new_external and not old_external),
                "accounts": [{"platform": platform, "is_active": values["is_active"], "handle_digest": _digest(values["handle"]), "external_id_digest": _digest(values["external_account_id"])} for platform, _, values in account_plans],
            },
        )
    return get_influencer_form(user=user, influencer_id=influencer.pk)
