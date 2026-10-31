"""Stored auction-spend reporting only; no collection or credential dependencies."""
from decimal import Decimal
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.integrations.ads_subject import mapping_allowed
from apps.integrations.models import AdsOAuthSession, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend
from apps.integrations.oauth_state_service import configuration_digest
from apps.permissions.ui_p6_scopes import analytics_dimensions_allowed
from apps.permissions.services import get_stored_business_read_scopes


def _locally_verified(mapping, sessions, digest):
    for session in sessions:
        if (session.store_id != mapping.store_id or session.integration_config_id != mapping.integration_config_id
                or session.token_id != mapping.token_id or not session.credential_id
                or session.config_fingerprint != digest):
            continue
        if not isinstance(session.binding_results, list) or not isinstance(session.candidates, list):
            continue
        bound = any(isinstance(item, dict) and item.get("mapping_id") == mapping.pk
                    and item.get("advertiser_id") == mapping.advertiser_id for item in session.binding_results)
        verified = any(isinstance(item, dict) and item.get("advertiser_id") == mapping.advertiser_id
                       and item.get("verify_state") == "verified" and item.get("verified_at")
                       and item.get("currency") == mapping.currency and item.get("timezone") == mapping.timezone
                       for item in session.candidates)
        if bound and verified:
            return True
    return False


def _gmv_max_report_rows(user, visible, names, date_from, date_to):
    from apps.integrations.gmv_max_read import GMVMaxSnapshotOverflow, stored_days
    try:
        return stored_days(user, visible, names, date_from, date_to), None
    except GMVMaxSnapshotOverflow:
        return None, "gmv_max_snapshot_limit_exceeded"


def daily_spend_report(user, query):
    if not user.is_active or user.user_type != "internal" or not user.tenant_id or user.tenant.status != "active":
        raise PermissionDenied("An active internal tenant is required.")
    mappings = TikTokAdsAdvertiserMapping.objects.filter(
        tenant_id=user.tenant_id, store__tenant_id=user.tenant_id,
        store__platform__tenant_id=user.tenant_id, store__platform__platform_type="tiktok",
        integration_config__tenant_id=user.tenant_id, integration_config__platform="tiktok",
    ).select_related("store__platform", "integration_config")
    visible = [m for m in mappings if mapping_allowed(user, m, "integrations.store.view", scope_resolver=get_stored_business_read_scopes)
               and analytics_dimensions_allowed(user, "analytics.view", {
                   "platform": "tiktok", "store_id": str(m.store_id), "country": m.store.country_code,
               })]
    sessions = list(AdsOAuthSession.objects.filter(tenant_id=user.tenant_id, status="bound",
        store_id__in={m.store_id for m in visible}, integration_config_id__in={m.integration_config_id for m in visible}).order_by('-created_at','-pk'))
    digests = {m.integration_config_id: configuration_digest(m.integration_config) for m in visible}
    names = {}
    for m in visible:
        for session in sessions:
            if _locally_verified(m, [session], digests[m.integration_config_id]):
                names[m.pk] = next((c.get('name','')[:200] for c in session.candidates
                    if isinstance(c,dict) and c.get('advertiser_id') == m.advertiser_id
                    and isinstance(c.get('name'),str)), '')
                break
    subjects = [{"mapping_id": m.pk, "store_id": m.store_id, "store_code": m.store.code,
                 "store_name": m.store.name, "advertiser_id": m.advertiser_id, "currency": m.currency,
                 "advertiser_name": names.get(m.pk, ''),
                 "mapping_timezone": m.timezone, "collection_enabled": m.enabled,
                 "local_evidence": "verified" if _locally_verified(m, sessions, digests[m.integration_config_id]) else "unverified"}
                for m in visible]
    for key in ("store_id", "advertiser_id"):
        if key in query:
            visible = [m for m in visible if getattr(m, key) == query[key]]
            if not visible:
                raise NotFound("Requested report subject does not exist.")
    by_id = {m.pk: m for m in visible}
    facts = TikTokAdsDailySpend.objects.filter(
        tenant_id=user.tenant_id, mapping_id__in=by_id,
        date__range=(query["date_from"], query["date_to"]),
    )
    stored = facts.count()
    days = (query["date_to"] - query["date_from"]).days + 1
    expected = len(visible) * days
    missing = expected - stored
    # Decimal accumulation avoids float coercion by SQLite test/preview backends.
    def currency_group():
        return {"amount": Decimal("0"), "stored": 0, "expected": 0, "matched": 0, "zero": 0, "mismatch": 0}
    currencies = {}
    for mapping in visible:
        currencies.setdefault(mapping.currency, currency_group())["expected"] += days
    for mapping_id, currency, spend in facts.values_list("mapping_id", "currency", "spend").iterator():
        item = currencies.setdefault(currency, currency_group())
        item["amount"] += spend
        item["stored"] += 1
        item["zero"] += spend == 0
        item["matched"] += currency == by_id[mapping_id].currency
        item["mismatch"] += currency != by_id[mapping_id].currency
    totals = []
    for currency, item in sorted(currencies.items()):
        complete = item["expected"] > 0 and item["matched"] == item["expected"] and not item["mismatch"]
        subtotal = str(item["amount"]) if item["stored"] else None
        totals.append({"currency": currency, "known_subtotal": subtotal, "total": subtotal if complete else None,
                       "expected_days": item["expected"], "stored_days": item["stored"],
                       "matching_currency_days": item["matched"], "missing_days": item["expected"] - item["matched"],
                       "explicit_zero": item["zero"], "currency_mismatch_days": item["mismatch"], "complete": complete})
    page, size = query["page"], query["page_size"]
    if page > max(1, (stored + size - 1) // size):
        raise NotFound("Requested page does not exist.")
    rows = []
    for fact in facts.order_by("-date", "mapping_id", "pk")[(page - 1) * size:page * size]:
        mapping = by_id[fact.mapping_id]
        rows.append({"id": fact.pk, "mapping_id": mapping.pk, "store_id": mapping.store_id,
                     "advertiser_name": names.get(mapping.pk, ''),
                     "store_code": mapping.store.code, "advertiser_id": mapping.advertiser_id,
                     "date": fact.date.isoformat(), "spend": str(fact.spend), "currency": fact.currency,
                     "fetched_at": fact.fetched_at.isoformat(),
                     "mapping_timezone": mapping.timezone, "metadata_basis": "current_mapping",
                     "currency_mismatch": fact.currency != mapping.currency})
    selected_subjects = [s for s in subjects if s["mapping_id"] in by_id]
    warnings = []
    if any(not s["collection_enabled"] for s in selected_subjects):
        warnings.append("collection_disabled")
    if any(s["local_evidence"] == "unverified" for s in selected_subjects):
        warnings.append("local_evidence_unverified")
    if any(t["currency_mismatch_days"] for t in totals):
        warnings.append("fact_currency_differs_from_current_mapping")
    gmv_rows, gmv_warning = _gmv_max_report_rows(user, visible, names, query['date_from'], query['date_to'])
    if gmv_warning:
        warnings.append(gmv_warning)
    return {"scope": "BASIC/AUCTION_CAMPAIGN", "excludes": ["GMVMax", "all_ads"],
            "gmv_max_snapshots": gmv_rows,
            "date_from": query["date_from"].isoformat(), "date_to": query["date_to"].isoformat(),
            "count": stored, "page": page, "page_size": size, "results": rows,
            "totals": totals, "complete": bool(totals) and all(t["complete"] for t in totals),
            "subjects": subjects, "selected_subjects": selected_subjects, "warnings": warnings,
            "total": None, "coverage": {"visible_mappings": len(visible), "mapping_days": expected,
                "stored": stored, "missing": missing, "explicit_zero": facts.filter(spend=0).count()},
            "metadata_basis": "current_mapping"}
