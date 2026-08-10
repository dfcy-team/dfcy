"""Read-only client for the external competitor-analysis service.

The development application owns the operator's decision, not competitor
collection or review storage.  This module therefore exposes only GET
operations, validates the small report contract at the boundary, and fails
closed when the upstream endpoint has not been configured.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import ContractViolation


COMPETITOR_PROVIDER_UNAVAILABLE = "COMPETITOR_PROVIDER_UNAVAILABLE"
COMPETITOR_CONTRACT_INVALID = "COMPETITOR_CONTRACT_INVALID"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class CompetitorProviderUnavailable(ContractViolation):
    """The read-only provider is not configured or cannot be reached."""

    def __init__(self, detail="Competitor analysis provider is unavailable."):
        super().__init__(
            detail,
            error_code=COMPETITOR_PROVIDER_UNAVAILABLE,
            status_code=503,
        )


class CompetitorContractError(ContractViolation):
    """The upstream response did not satisfy the agreed report contract."""

    def __init__(self, detail="Competitor analysis response is invalid."):
        super().__init__(
            detail,
            error_code=COMPETITOR_CONTRACT_INVALID,
            status_code=502,
        )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompetitorContractError(f"Competitor {label} must be an object.")
    return value


def _text(value: Any, label: str, *, required=True, max_length=None) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        # IDs in upstream systems are commonly numeric.  Keep IDs stable as
        # strings while rejecting arbitrary objects and arrays.
        if label.endswith("_id") and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        else:
            raise CompetitorContractError(f"Competitor {label} must be a string.")
    value = value.strip()
    if required and not value:
        raise CompetitorContractError(f"Competitor {label} is required.")
    if max_length and len(value) > max_length:
        raise CompetitorContractError(f"Competitor {label} is too long.")
    return value


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise CompetitorContractError(f"Competitor {label} must be a non-negative integer.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise CompetitorContractError(f"Competitor {label} must be a non-negative integer.")
    if number < 0 or (isinstance(value, float) and value != number):
        raise CompetitorContractError(f"Competitor {label} must be a non-negative integer.")
    return number


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise CompetitorContractError(f"Competitor {label} must be an array.")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise CompetitorContractError(f"Competitor {label} items must be strings.")
        item = item.strip()
        if item:
            result.append(item)
    return result


def _timestamp(value: Any, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise CompetitorContractError(f"Competitor {label} must be an ISO timestamp.") from exc
    else:
        raise CompetitorContractError(f"Competitor {label} must be an ISO timestamp.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_timestamp(value: Any, label: str) -> str | None:
    if value in (None, ""):
        return None
    return _timestamp(value, label)


def _unwrap_payload(payload: Any, *, collection=False, evidence=False) -> Any:
    """Accept the internal success envelope without coupling to its wrapper."""

    if isinstance(payload, Mapping) and "data" in payload:
        payload = payload["data"]
    if collection and isinstance(payload, Mapping):
        for key in ("results", "reports", "items"):
            if key in payload:
                return payload
    if evidence and isinstance(payload, Mapping):
        for key in ("results", "evidence", "items"):
            if key in payload:
                return payload
    if isinstance(payload, Mapping) and not collection and not evidence and "report" in payload:
        return payload["report"]
    return payload


def _statistics(raw: Any) -> dict[str, int]:
    source = _mapping(raw or {}, "statistics")
    aliases = {
        "input": ("input", "input_reviews", "total", "total_reviews"),
        "valid": ("valid", "valid_reviews", "effective", "effective_reviews"),
        "positive": ("positive", "positive_reviews"),
        "neutral": ("neutral", "neutral_reviews"),
        "negative": ("negative", "negative_reviews"),
    }
    result = {}
    for target, keys in aliases.items():
        present = next((source[key] for key in keys if key in source), None)
        if present is None and not any(key in source for key in keys):
            raise CompetitorContractError(f"Competitor statistics.{target} is required.")
        value = present
        result[target] = _non_negative_int(value, f"statistics.{target}")
    if not any(key in source for key in aliases["valid"]) and result["input"]:
        # The provider may omit valid_reviews when all input is valid, but it
        # must never silently claim more valid reviews than were provided.
        result["valid"] = result["input"]
    if result["valid"] > result["input"] and result["input"]:
        raise CompetitorContractError("Competitor valid review count exceeds input count.")
    if sum(result[field] for field in ("positive", "neutral", "negative")) > result["valid"]:
        raise CompetitorContractError("Competitor sentiment counts exceed valid review count.")
    return result


def _insights(raw: Any) -> dict[str, list[str]]:
    source = _mapping(raw or {}, "insights")
    return {
        "strengths": _string_list(source.get("strengths", source.get("strengths_list", [])), "insights.strengths"),
        "pain_points": _string_list(source.get("pain_points", source.get("painpoints", [])), "insights.pain_points"),
        "recommendations": _string_list(source.get("recommendations", source.get("improvement_suggestions", [])), "insights.recommendations"),
    }


def _attributes(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        # A few provider versions keyed attributes by code.  Normalize them
        # to the agreed array without copying unrelated provider fields.
        raw = [dict(item, code=code) if isinstance(item, Mapping) else item for code, item in raw.items()]
    if not isinstance(raw, (list, tuple)):
        raise CompetitorContractError("Competitor attributes must be an array.")
    result = []
    for index, item in enumerate(raw):
        source = _mapping(item, f"attributes[{index}]")
        result.append(
            {
                "code": _text(source.get("code"), f"attributes[{index}].code", max_length=80),
                "name": _text(source.get("name"), f"attributes[{index}].name", max_length=160),
                "mentions": _non_negative_int(source.get("mentions", source.get("mentioned", 0)), f"attributes[{index}].mentions"),
                "positive": _non_negative_int(source.get("positive", 0), f"attributes[{index}].positive"),
                "neutral": _non_negative_int(source.get("neutral", 0), f"attributes[{index}].neutral"),
                "negative": _non_negative_int(source.get("negative", 0), f"attributes[{index}].negative"),
                "conclusion": _text(source.get("conclusion"), f"attributes[{index}].conclusion", required=False, max_length=4000),
            }
        )
    return result


def _tenant_hint(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    value = raw.get("tenant_id")
    if value is not None:
        return str(value), None
    value = raw.get("tenant")
    if isinstance(value, Mapping):
        identifier = value.get("id", value.get("tenant_id"))
        code = value.get("code", value.get("tenant_code"))
        return str(identifier) if identifier is not None else None, str(code) if code is not None else None
    if value is not None:
        return str(value), None
    code = raw.get("tenant_code")
    return None, str(code) if code is not None else None


def _verify_tenant(raw: Mapping[str, Any], tenant) -> None:
    identifier, code = _tenant_hint(raw)
    if identifier is not None and identifier not in {str(tenant.pk), str(getattr(tenant, "id", ""))}:
        raise CompetitorContractError("Competitor report tenant does not match the current tenant.")
    if code is not None and code != str(getattr(tenant, "code", "")):
        raise CompetitorContractError("Competitor report tenant does not match the current tenant.")


def _verify_payload_tenant(payload: Any, tenant) -> None:
    """Check tenant hints on both an envelope and its nested data object."""

    if not isinstance(payload, Mapping):
        return
    _verify_tenant(payload, tenant)
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        _verify_tenant(nested, tenant)


def normalize_report(raw: Any, *, tenant=None) -> dict[str, Any]:
    source = _mapping(raw, "report")
    if tenant is not None:
        _verify_tenant(source, tenant)
    required_sections = {
        "statistics",
        "summary",
        "insights",
        "attributes",
        "cautions",
    }
    missing_sections = sorted(required_sections.difference(source))
    if missing_sections:
        raise CompetitorContractError(
            "Competitor report is missing required fields: " + ", ".join(missing_sections)
        )
    required_metadata = (
        "report_id",
        "task_id",
        "status",
        "platform",
        "site",
        "product_id",
        "product_title",
        "completed_at",
        "data_updated_at",
    )
    missing_metadata = [field for field in required_metadata if field not in source]
    if missing_metadata:
        raise CompetitorContractError(
            "Competitor report is missing required fields: " + ", ".join(missing_metadata)
        )
    status = _text(source.get("status"), "status", max_length=40).casefold()
    return {
        "report_id": _text(source.get("report_id"), "report_id", max_length=160),
        "task_id": _text(source.get("task_id"), "task_id", max_length=160),
        "status": status,
        "platform": _text(source.get("platform"), "platform", max_length=50),
        "site": _text(source.get("site"), "site", max_length=40),
        "product_id": _text(source.get("product_id"), "product_id", max_length=160),
        "product_title": _text(source.get("product_title"), "product_title", max_length=300),
        "completed_at": _timestamp(source.get("completed_at"), "completed_at"),
        "data_updated_at": _timestamp(source.get("data_updated_at", source.get("updated_at")), "data_updated_at"),
        "statistics": _statistics(source.get("statistics")),
        "summary": _text(source.get("summary"), "summary", required=False, max_length=20000),
        "insights": _insights(source.get("insights")),
        "attributes": _attributes(source.get("attributes", [])),
        "cautions": _string_list(source.get("cautions", source.get("注意事项", [])), "cautions"),
    }


def _items_payload(payload: Any, *, key: str) -> tuple[list[Any], dict[str, Any]]:
    if isinstance(payload, list):
        return payload, {}
    source = _mapping(payload, key)
    items = None
    for candidate in (("results", "reports", "items") if key == "report list" else ("results", "evidence", "items")):
        if candidate in source:
            items = source[candidate]
            break
    if not isinstance(items, list):
        raise CompetitorContractError(f"Competitor {key} must contain an items array.")
    metadata = {name: source[name] for name in ("count", "next", "previous", "page", "page_size", "total_pages") if name in source}
    return items, metadata


class CompetitorReportClient:
    """Small GET-only client; ``opener`` is injectable for deterministic tests."""

    def __init__(self, *, base_url=None, timeout=None, opener=None):
        configured = (
            base_url
            if base_url is not None
            else (
                getattr(settings, "COMPETITOR_REPORT_BASE_URL", "")
                or getattr(settings, "COMPETITOR_REPORT_API_BASE_URL", "")
            )
        )
        self.base_url = str(configured or "").strip().rstrip("/")
        configured_timeout = timeout
        if configured_timeout is None:
            configured_timeout = getattr(settings, "COMPETITOR_REPORT_TIMEOUT_SECONDS", None)
            if configured_timeout in (None, ""):
                configured_timeout = getattr(settings, "COMPETITOR_REPORT_API_TIMEOUT_SECONDS", 5)
        try:
            self.timeout = max(1, min(int(configured_timeout), 60))
        except (TypeError, ValueError):
            self.timeout = 5
        self.opener = opener or urlopen

    def _ensure_configured(self):
        if not self.base_url:
            raise CompetitorProviderUnavailable(
                "Competitor analysis provider is not configured; report access is disabled."
            )

    def _get(self, path, *, tenant, params=None):
        self._ensure_configured()
        relative = str(path).lstrip("/")
        query = dict(params or {})
        query.pop("tenant", None)
        query.pop("tenant_id", None)
        # The tenant is supplied as a trusted server-side header.  A query
        # parameter from a browser must never be able to select another tenant.
        url = f"{self.base_url}/{relative}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"
        headers = {
            "Accept": "application/json",
            "X-Tenant-ID": str(getattr(tenant, "pk", "")),
            "X-Tenant-Code": str(getattr(tenant, "code", "")),
        }
        request = Request(url, headers=headers, method="GET")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise CompetitorProviderUnavailable("Competitor analysis provider request failed.") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise CompetitorProviderUnavailable("Competitor analysis provider response is too large.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CompetitorContractError("Competitor analysis provider returned invalid JSON.") from exc
        return payload

    def list_reports(self, *, tenant, params=None) -> dict[str, Any]:
        raw_payload = self._get("reports/", tenant=tenant, params=params)
        _verify_payload_tenant(raw_payload, tenant)
        payload = _unwrap_payload(raw_payload, collection=True)
        items, metadata = _items_payload(payload, key="report list")
        reports = [normalize_report(item, tenant=tenant) for item in items]
        return {"results": reports, **metadata}

    def get_report(self, report_id, *, tenant) -> dict[str, Any]:
        report_id = _text(report_id, "report_id", max_length=160)
        raw_payload = self._get(f"reports/{quote(report_id, safe='')}/", tenant=tenant)
        _verify_payload_tenant(raw_payload, tenant)
        payload = _unwrap_payload(raw_payload)
        return normalize_report(payload, tenant=tenant)

    def list_evidence(self, report_id, *, tenant, page=1, page_size=20) -> dict[str, Any]:
        try:
            page = max(1, int(page))
            page_size = max(1, min(int(page_size), 100))
        except (TypeError, ValueError):
            raise CompetitorContractError("Evidence pagination values must be positive integers.")
        raw_payload = self._get(
            f"reports/{quote(_text(report_id, 'report_id', max_length=160), safe='')}/evidence/",
            tenant=tenant,
            params={"page": page, "page_size": page_size},
        )
        # Some provider versions repeat tenant context on the evidence
        # envelope.  Enforce it when present, while allowing a bare paginated
        # array for older read-only endpoints.
        _verify_payload_tenant(raw_payload, tenant)
        payload = _unwrap_payload(raw_payload, evidence=True)
        items, metadata = _items_payload(payload, key="evidence")
        # Evidence belongs to the upstream service.  Validate its envelope and
        # return a bounded, opaque representation without storing it locally.
        normalized = []
        for index, item in enumerate(items):
            source = _mapping(item, f"evidence[{index}]")
            evidence_id = source.get("evidence_id", source.get("id"))
            normalized.append(
                {
                    "evidence_id": _text(evidence_id, f"evidence[{index}].evidence_id", max_length=160),
                    "attribute_code": _text(source.get("attribute_code", source.get("attribute", "")), f"evidence[{index}].attribute_code", required=False, max_length=80),
                    "review": _text(source.get("review", source.get("text", source.get("original_text", ""))), f"evidence[{index}].review", required=False, max_length=10000),
                    "sentiment": _text(source.get("sentiment", ""), f"evidence[{index}].sentiment", required=False, max_length=30).casefold(),
                }
            )
        return {"results": normalized, **metadata}

    @staticmethod
    def snapshot_payload(report: Mapping[str, Any]) -> dict[str, Any]:
        """Return the immutable structured portion used for audit decisions."""

        return {
            "report_id": report["report_id"],
            "task_id": report["task_id"],
            "status": report["status"],
            "platform": report["platform"],
            "site": report["site"],
            "product_id": report["product_id"],
            "product_title": report["product_title"],
            "completed_at": report["completed_at"],
            "data_updated_at": report["data_updated_at"],
            "statistics": report["statistics"],
            "summary": report["summary"],
            "insights": report["insights"],
            "attributes": report["attributes"],
            "cautions": report["cautions"],
        }


def report_datetime(value: str) -> datetime:
    """Convert a normalized timestamp into a timezone-aware Django value."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)
