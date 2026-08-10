"""Fail-closed local credential leases for the SC-SUPPLY-FLOW UAT fixture.

This module is deliberately separate from the purchasing business services.  It
only changes the short-lived credential marker and password hash on the exact
synthetic identities created by UAT-1.  Plaintext passwords exist in memory
only long enough for an injected terminal sink to display them once.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.masterdata.models import SupplierMaster
from apps.permissions.models import DataScope, UserRole
from apps.purchasing.uat_data import (
    ALL_CONSOLIDATION_PERMISSIONS,
    ALL_PACKING_PERMISSIONS,
    ALL_PURCHASE_PERMISSIONS,
    ALL_SHIPMENT_PERMISSIONS,
    DATA_VERSION,
    TENANT_CODES,
    UATDataError,
    check_fixture,
    make_context,
    validate_local_database,
)
from apps.tenants.models import Tenant


MAX_DURATION_HOURS = Decimal("8")
DEFAULT_DURATION_HOURS = Decimal("8")


@dataclass(frozen=True)
class UATCredentialSubject:
    username: str
    tenant_code: str
    user_type: str
    role_code: str | None = None
    scope_type: str | None = None
    scope_config: dict | None = None
    supplier_code: str | None = None
    permissions: tuple[str, ...] = ()


def _internal(
    username: str,
    role_code: str,
    scope_type: str,
    permissions: Iterable[str],
    scope_config: dict | None = None,
) -> UATCredentialSubject:
    return UATCredentialSubject(
        username=username,
        tenant_code="SC-UAT-A",
        user_type=CustomUser.UserType.INTERNAL,
        role_code=role_code,
        scope_type=scope_type,
        scope_config=scope_config or {},
        permissions=tuple(permissions),
    )


ALLOWED_SUBJECTS: dict[str, UATCredentialSubject] = {
    "SC-UAT-A-procurement": _internal(
        "SC-UAT-A-procurement", "sc-uat-a-procurement", DataScope.ScopeType.ALL, ALL_PURCHASE_PERMISSIONS
    ),
    "SC-UAT-A-packer": _internal(
        "SC-UAT-A-packer", "sc-uat-a-packer", DataScope.ScopeType.ALL, ALL_PACKING_PERMISSIONS
    ),
    "SC-UAT-A-consolidator": _internal(
        "SC-UAT-A-consolidator", "sc-uat-a-consolidator", DataScope.ScopeType.CUSTOM, ALL_CONSOLIDATION_PERMISSIONS
    ),
    "SC-UAT-A-shipper": _internal(
        "SC-UAT-A-shipper", "sc-uat-a-shipper", DataScope.ScopeType.CUSTOM, ALL_SHIPMENT_PERMISSIONS
    ),
    "SC-UAT-A-auditor": _internal(
        "SC-UAT-A-auditor",
        "sc-uat-a-auditor",
        DataScope.ScopeType.ALL,
        (
            "supply.purchase_order.view",
            "supply.packing.view",
            "supply.consolidation.view",
            "supply.consolidation_site.view",
            "supply.shipment.view",
        ),
    ),
    "SC-UAT-A-scope-own": _internal(
        "SC-UAT-A-scope-own", "sc-uat-a-scope-own", DataScope.ScopeType.OWN, ("supply.consolidation.view",)
    ),
    "SC-UAT-A-scope-department": _internal(
        "SC-UAT-A-scope-department", "sc-uat-a-scope-department", DataScope.ScopeType.DEPARTMENT, ("supply.consolidation.view",)
    ),
    "SC-UAT-A-scope-incomplete": _internal(
        "SC-UAT-A-scope-incomplete",
        "sc-uat-a-scope-incomplete",
        DataScope.ScopeType.CUSTOM,
        ("supply.consolidation.view",),
        {"supplier_ids": [1]},
    ),
    # The negative subject is deliberately whitelisted so UAT can prove that
    # its role-less account cannot write; it is still never granted a role.
    "SC-UAT-A-unauthorized": UATCredentialSubject(
        username="SC-UAT-A-unauthorized",
        tenant_code="SC-UAT-A",
        user_type=CustomUser.UserType.INTERNAL,
    ),
    "SC-UAT-A-supplier-a": UATCredentialSubject(
        username="SC-UAT-A-supplier-a",
        tenant_code="SC-UAT-A",
        user_type=CustomUser.UserType.EXTERNAL,
        supplier_code="SC-UAT-SUP-A",
    ),
    "SC-UAT-A-supplier-b": UATCredentialSubject(
        username="SC-UAT-A-supplier-b",
        tenant_code="SC-UAT-A",
        user_type=CustomUser.UserType.EXTERNAL,
        supplier_code="SC-UAT-SUP-B",
    ),
    "SC-UAT-A-supplier-c": UATCredentialSubject(
        username="SC-UAT-A-supplier-c",
        tenant_code="SC-UAT-A",
        user_type=CustomUser.UserType.EXTERNAL,
        supplier_code="SC-UAT-SUP-C",
    ),
    # Tenant B is opt-in and only exposes its read-only negative-validation
    # subject by default; no broad cross-tenant activation is supported.
    "SC-UAT-B-auditor": UATCredentialSubject(
        username="SC-UAT-B-auditor",
        tenant_code="SC-UAT-B",
        user_type=CustomUser.UserType.INTERNAL,
        role_code="sc-uat-b-auditor",
        scope_type=DataScope.ScopeType.ALL,
        scope_config={},
        permissions=(
            "supply.purchase_order.view",
            "supply.packing.view",
            "supply.consolidation.view",
            "supply.consolidation_site.view",
            "supply.shipment.view",
        ),
    ),
}


class CredentialToolError(UATDataError):
    """Safe user-facing error that never contains a generated secret."""


def _duration_seconds(duration_hours: Decimal | str | int | float) -> int:
    try:
        value = Decimal(str(duration_hours))
    except (InvalidOperation, ValueError) as exc:
        raise CredentialToolError("Credential duration must be a positive number of hours.") from exc
    if not value.is_finite() or value <= 0 or value > MAX_DURATION_HOURS:
        raise CredentialToolError("Credential duration must be no more than 8 hours.")
    seconds = int(value * Decimal("3600"))
    if seconds <= 0:
        raise CredentialToolError("Credential duration is too short.")
    return seconds


def _marker_matches(tenant: Tenant, context) -> bool:
    expected = f"{tenant.code} | {context.data_version} | {context.payload_hash}"
    return tenant.name == expected and tenant.code in TENANT_CODES and tenant.status == Tenant.Status.ACTIVE


def _resolve_subjects(
    usernames: Iterable[str] | None = None,
    *,
    tenant_code: str | None = None,
    all_allowed: bool = False,
) -> list[UATCredentialSubject]:
    requested = [str(item or "").strip() for item in (usernames or [])]
    if any(not item for item in requested) or len(set(requested)) != len(requested):
        raise CredentialToolError("Username selection must contain unique non-empty values.")
    if all_allowed and requested:
        raise CredentialToolError("Choose explicit usernames or --all-allowed, not both.")
    selected_tenant = str(tenant_code or "SC-UAT-A").strip()
    if selected_tenant not in TENANT_CODES:
        raise CredentialToolError("Only SC-UAT-A or SC-UAT-B can be selected.")
    if all_allowed:
        requested = [
            subject.username
            for subject in ALLOWED_SUBJECTS.values()
            if subject.tenant_code == selected_tenant
        ]
    if not requested:
        raise CredentialToolError("Explicit usernames or --all-allowed are required.")
    subjects = []
    for username in requested:
        subject = ALLOWED_SUBJECTS.get(username)
        if subject is None or subject.tenant_code != selected_tenant:
            raise CredentialToolError(f"Username {username!r} is outside the frozen UAT allowlist.")
        subjects.append(subject)
    return subjects


def _preflight_fixture(context) -> None:
    try:
        check_fixture(context)
    except Exception as exc:
        if isinstance(exc, CredentialToolError):
            raise
        raise CredentialToolError("UAT fixture check failed; no credential change was made.") from exc


def _load_users(subjects: list[UATCredentialSubject], context, *, lock: bool = False) -> list[CustomUser]:
    usernames = [subject.username for subject in subjects]
    query = CustomUser.objects.select_related("tenant")
    if lock:
        query = query.select_for_update()
    users = list(query.filter(username__in=usernames).order_by("username"))
    found = {user.username for user in users}
    if found != set(usernames):
        raise CredentialToolError("One or more requested UAT identities do not exist.")
    by_name = {user.username: user for user in users}
    ordered = [by_name[subject.username] for subject in subjects]
    for subject, user in zip(subjects, ordered):
        if user.tenant.code != subject.tenant_code or not _marker_matches(user.tenant, context):
            raise CredentialToolError(f"UAT marker/tenant check failed for {subject.username}.")
        if not user.is_active or user.is_superuser or user.is_staff or user.user_type == CustomUser.UserType.RPA:
            raise CredentialToolError(f"UAT identity {subject.username} is inactive or privileged.")
        if user.user_type != subject.user_type:
            raise CredentialToolError(f"UAT identity {subject.username} has an unexpected user type.")
        _validate_role_and_binding(user, subject)
    return ordered


def _validate_role_and_binding(user: CustomUser, subject: UATCredentialSubject) -> None:
    active_roles = list(
        UserRole.objects.filter(user=user, tenant=user.tenant, role__status="active")
        .select_related("role")
        .prefetch_related("role__permissions")
    )
    if subject.supplier_code:
        profile = ExternalUserProfile.objects.filter(user=user, tenant=user.tenant).first()
        supplier = SupplierMaster.objects.filter(tenant=user.tenant, code=subject.supplier_code).first()
        if profile is None or supplier is None or profile.supplier_id != supplier.id or active_roles:
            raise CredentialToolError(f"Supplier binding/role check failed for {subject.username}.")
        return
    if subject.role_code is None:
        if active_roles:
            raise CredentialToolError(f"Negative UAT identity {subject.username} unexpectedly has a role.")
        return
    if len(active_roles) != 1 or active_roles[0].role.code != subject.role_code:
        raise CredentialToolError(f"UAT identity {subject.username} must have exactly its frozen role.")
    role = active_roles[0].role
    permission_codes = set(role.permissions.values_list("code", flat=True))
    if permission_codes != set(subject.permissions):
        raise CredentialToolError(f"UAT role permission matrix failed for {subject.username}.")
    scopes = list(DataScope.objects.filter(tenant=user.tenant, role=role))
    if len(scopes) != 1 or scopes[0].scope_type != subject.scope_type or scopes[0].config != (subject.scope_config or {}):
        raise CredentialToolError(f"UAT DataScope matrix failed for {subject.username}.")


def _metadata(user: CustomUser, subject: UATCredentialSubject, *, now=None) -> dict:
    current = now or timezone.now()
    status = str(getattr(user, "uat_credential_status", "never") or "never").strip().lower()
    if status == "active" and (not user.uat_credential_expires_at or user.uat_credential_expires_at <= current):
        status = "expired"
    return {
        "username": user.username,
        "tenant": user.tenant.code,
        "user_type": user.user_type,
        "role": subject.role_code,
        "supplier": subject.supplier_code,
        "status": status,
        # Return stable JSON-native values so callers cannot accidentally
        # stringify an internal model object (and command/API output stays
        # deterministic without a custom encoder).
        "activated_at": user.uat_credential_activated_at.isoformat() if user.uat_credential_activated_at else None,
        "expires_at": user.uat_credential_expires_at.isoformat() if user.uat_credential_expires_at else None,
        "batch_digest": user.uat_credential_batch_digest or None,
    }


def _new_password(user: CustomUser) -> str:
    for _ in range(8):
        password = secrets.token_urlsafe(24)
        try:
            validate_password(password, user)
        except DjangoValidationError:
            continue
        return password
    raise CredentialToolError("Secure password generation failed validation; no change was made.")


def _batch_digest(context, users: list[CustomUser], now) -> str:
    nonce = secrets.token_bytes(32)
    material = ":".join(
        [context.data_version, context.payload_hash, now.isoformat(), ",".join(str(user.pk) for user in users), nonce.hex()]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def activate_credentials(
    context,
    usernames: Iterable[str] | None = None,
    *,
    tenant_code: str | None = None,
    all_allowed: bool = False,
    duration_hours: Decimal | str | int | float = DEFAULT_DURATION_HOURS,
    apply: bool = False,
    secret_sink: Callable[[list[tuple[str, str]]], None] | None = None,
) -> dict:
    """Dry-run or atomically activate one exact UAT subject batch."""

    subjects = _resolve_subjects(usernames, tenant_code=tenant_code, all_allowed=all_allowed)
    seconds = _duration_seconds(duration_hours)
    _preflight_fixture(context)
    users = _load_users(subjects, context)
    now = timezone.now()
    if not apply:
        return {
            "action": "activate",
            "status": "DRY_RUN",
            "duration_hours": str(Decimal(seconds) / Decimal("3600")),
            "users": [_metadata(user, subject, now=now) for user, subject in zip(users, subjects)],
        }
    if secret_sink is None:
        raise CredentialToolError("Interactive secret sink is required for activation; no change was made.")
    passwords: list[tuple[str, str]] = []
    metadata: list[dict] = []
    with transaction.atomic():
        users = _load_users(subjects, context, lock=True)
        now = timezone.now()
        for user in users:
            if user.uat_credential_status == "active" or user.uat_credential_batch_digest or user.uat_credential_expires_at:
                raise CredentialToolError(f"UAT identity {user.username} already has a credential lease; revoke first.")
            if user.has_usable_password():
                raise CredentialToolError(f"UAT identity {user.username} is not an untouched unusable placeholder.")
        batch_digest = _batch_digest(context, users, now)
        expires_at = now + timedelta(seconds=seconds)
        for subject, user in zip(subjects, users):
            password = _new_password(user)
            passwords.append((user.username, password))
            user.set_password(password)
            user.uat_credential_activated_at = now
            user.uat_credential_expires_at = expires_at
            user.uat_credential_batch_digest = batch_digest
            user.uat_credential_status = "active"
            user.save(update_fields=[
                "password", "uat_credential_activated_at", "uat_credential_expires_at",
                "uat_credential_batch_digest", "uat_credential_status", "updated_at",
            ])
            metadata.append(_metadata(user, subject, now=now))
        try:
            # The sink is intentionally injected; the command supplies a
            # one-time interactive terminal writer and tests supply a silent
            # in-memory collector.  Any sink failure aborts the transaction.
            secret_sink(passwords)
        except Exception as exc:
            raise CredentialToolError("One-time credential delivery failed; activation rolled back.") from exc
    return {"action": "activate", "status": "ACTIVATED", "users": metadata}


def revoke_credentials(
    context,
    usernames: Iterable[str] | None = None,
    *,
    tenant_code: str | None = None,
    all_allowed: bool = False,
    apply: bool = False,
) -> dict:
    """Dry-run or atomically revoke exact UAT leases without broad updates."""

    subjects = _resolve_subjects(usernames, tenant_code=tenant_code, all_allowed=all_allowed)
    _preflight_fixture(context)
    users = _load_users(subjects, context)
    now = timezone.now()
    if not apply:
        return {"action": "revoke", "status": "DRY_RUN", "users": [_metadata(user, subject, now=now) for user, subject in zip(users, subjects)]}
    metadata: list[dict] = []
    with transaction.atomic():
        users = _load_users(subjects, context, lock=True)
        for subject, user in zip(subjects, users):
            user.set_unusable_password()
            user.uat_credential_activated_at = None
            user.uat_credential_expires_at = None
            user.uat_credential_batch_digest = ""
            user.uat_credential_status = "revoked"
            user.save(update_fields=[
                "password", "uat_credential_activated_at", "uat_credential_expires_at",
                "uat_credential_batch_digest", "uat_credential_status", "updated_at",
            ])
            metadata.append(_metadata(user, subject, now=now))
    return {"action": "revoke", "status": "REVOKED", "users": metadata}


def status_credentials(
    context,
    usernames: Iterable[str] | None = None,
    *,
    tenant_code: str | None = None,
    all_allowed: bool = False,
) -> dict:
    """Return non-secret lease metadata for an exact subject selection."""

    subjects = _resolve_subjects(usernames, tenant_code=tenant_code, all_allowed=all_allowed)
    _preflight_fixture(context)
    users = _load_users(subjects, context)
    return {"action": "status", "status": "OK", "users": [_metadata(user, subject) for user, subject in zip(users, subjects)]}


def build_context(data_version: str = DATA_VERSION, payload: str = "fixture-v1"):
    return make_context(data_version, payload)
