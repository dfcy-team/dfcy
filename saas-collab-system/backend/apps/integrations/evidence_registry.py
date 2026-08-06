"""Masked-only evidence registry for the real Sandbox OAuth technical readiness items.

Evidence rows never store credential material: only masks, references, sources,
confirmer names, confirmation timestamps and contract versions. Registration is
append-only; a new registration supersedes the previous current row.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import MarketplaceOAuthEvidence, oauth_evidence_write

PER_PLATFORM_KEYS = {
    MarketplaceOAuthEvidence.EvidenceKey.APP_IDENTITY,
    MarketplaceOAuthEvidence.EvidenceKey.ENDPOINT_CONTRACT,
    MarketplaceOAuthEvidence.EvidenceKey.CALLBACK_URL,
}
SHARED_KEYS = {
    MarketplaceOAuthEvidence.EvidenceKey.CUSTODY_CONTRACT,
    MarketplaceOAuthEvidence.EvidenceKey.NETWORK_EGRESS,
    MarketplaceOAuthEvidence.EvidenceKey.SECURITY_CONFIRMATION,
}
REAL_SANDBOX_PLATFORMS = ("shopee", "tiktok")
SHARED_PLATFORM = "shared"

# Credential-shaped key names are rejected outright so raw material can never be
# parked inside a "masked" payload by accident.
FORBIDDEN_MASKED_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "private_key",
    "partner_key",
    "cookie",
    "session",
    "auth_code",
    "authorization_code",
)


def _scan_for_forbidden_keys(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in FORBIDDEN_MASKED_KEY_MARKERS):
                raise ValidationError(f"Evidence payload key '{path}{key}' looks like credential material.")
            _scan_for_forbidden_keys(item, f"{path}{key}.")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_for_forbidden_keys(item, f"{path}{index}.")


def _validate_masked_value(masked_value):
    if not isinstance(masked_value, dict):
        raise ValidationError("Evidence masked_value must be an object of masks and references.")
    _scan_for_forbidden_keys(masked_value)


def register_oauth_evidence(
    *,
    evidence_key,
    platform,
    readiness,
    masked_value,
    source,
    confirmed_by,
    contract_version,
    environment=MarketplaceOAuthEvidence.Environment.SANDBOX,
):
    """Append a new evidence row and supersede the previous current row atomically."""
    if evidence_key in PER_PLATFORM_KEYS and platform not in REAL_SANDBOX_PLATFORMS:
        raise ValidationError("Per-platform evidence must be registered for shopee or tiktok.")
    if evidence_key in SHARED_KEYS and platform != SHARED_PLATFORM:
        raise ValidationError("Shared evidence must be registered with platform='shared'.")
    if readiness not in MarketplaceOAuthEvidence.Readiness.values:
        raise ValidationError("Evidence readiness must be pending or ready.")
    _validate_masked_value(masked_value)
    if not str(source).strip() or not str(confirmed_by).strip():
        raise ValidationError("Evidence requires a source and a confirmer.")

    with transaction.atomic():
        with oauth_evidence_write():
            MarketplaceOAuthEvidence.objects.filter(
                evidence_key=evidence_key,
                platform=platform,
                environment=environment,
                is_current=True,
            ).update(is_current=False, superseded_at=timezone.now())
            return MarketplaceOAuthEvidence.objects.create(
                evidence_key=evidence_key,
                platform=platform,
                environment=environment,
                readiness=readiness,
                masked_value=masked_value,
                source=str(source).strip()[:200],
                confirmed_by=str(confirmed_by).strip()[:120],
                contract_version=str(contract_version).strip()[:40],
            )


def current_oauth_evidence(evidence_key, platform, environment=MarketplaceOAuthEvidence.Environment.SANDBOX):
    return MarketplaceOAuthEvidence.objects.filter(
        evidence_key=evidence_key,
        platform=platform,
        environment=environment,
        is_current=True,
    ).order_by("-id").first()


def _required_pairs(environment):
    pairs = []
    for key in PER_PLATFORM_KEYS:
        for platform in REAL_SANDBOX_PLATFORMS:
            pairs.append((key, platform))
    for key in SHARED_KEYS:
        pairs.append((key, SHARED_PLATFORM))
    return [(key, platform, environment) for key, platform in pairs]


def real_sandbox_evidence_ready(environment=MarketplaceOAuthEvidence.Environment.SANDBOX):
    """True only when every A2-00 technical preparation item is current and ready."""
    for key, platform, env in _required_pairs(environment):
        evidence = current_oauth_evidence(key, platform, env)
        if evidence is None or evidence.readiness != MarketplaceOAuthEvidence.Readiness.READY:
            return False
    return True


def evidence_readiness_summary(environment=MarketplaceOAuthEvidence.Environment.SANDBOX):
    summary = []
    for key, platform, env in _required_pairs(environment):
        evidence = current_oauth_evidence(key, platform, env)
        summary.append(
            {
                "evidence_key": key,
                "platform": platform,
                "environment": env,
                "readiness": evidence.readiness if evidence else MarketplaceOAuthEvidence.Readiness.PENDING,
                "contract_version": evidence.contract_version if evidence else "",
                "confirmed_by": evidence.confirmed_by if evidence else "",
            }
        )
    return summary
