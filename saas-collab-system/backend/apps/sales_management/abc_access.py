"""Read published ABC snapshots without recalculating sales on page requests."""
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db.models import Case, Q, Value, When
from django.utils import timezone
from apps.masterdata.models import InventoryABCRun, InventoryABCEntry, InventoryObservationSettings
from apps.products.models import ProductSKU


ABC_POLICY_VERSION = "composite_revenue_units_v1_20261120"


def published_run(actor, country):
    runs = InventoryABCRun.objects.filter(tenant_id=actor.tenant_id, country_id=country.pk)
    current_policy = Q(config__classification_basis="composite", config__policy_version=ABC_POLICY_VERSION)
    latest = runs.annotate(
        policy_priority=Case(When(status__in=("queued", "building"), then=Value(0)), When(current_policy, then=Value(1)), default=Value(2))
    ).order_by("policy_priority", "-created_at", "-pk").first()
    latest_composite = latest if latest and latest.config.get("classification_basis") == "composite" and latest.config.get("policy_version") == ABC_POLICY_VERSION else None
    settings = InventoryObservationSettings.objects.filter(tenant_id=actor.tenant_id).first()
    enabled = settings.abc_enabled if settings else True
    run = None
    if enabled and latest and latest.policy_priority <= 1:
        preferred_status = Case(When(status="ready", then=Value(0)), default=Value(1))
        run = runs.filter(current_policy, status__in=("ready", "partial")).order_by(
            preferred_status, "-cutoff_date", "-completed_at", "-pk"
        ).first()
    composite_pending = bool(enabled and run is None and latest)
    expected = {
        "window_days": settings.abc_window_days,
        "a_percent": f"{settings.abc_a_percent:.2f}",
        "b_percent": f"{settings.abc_b_percent:.2f}",
        "stability_days": settings.abc_stability_days,
        "new_product_observation_days": settings.new_product_observation_days,
    } if settings else {}
    config_pending = bool(run and expected and any(str(run.config.get(key)) != str(value) for key, value in expected.items()))
    try:
        today = timezone.now().astimezone(ZoneInfo(country.timezone)).date()
    except (ValueError, ZoneInfoNotFoundError):
        today = timezone.localdate()
    meta = {
        "run_id": run.pk if run else None,
        "enabled": enabled,
        "status": run.status if run else ("pending" if composite_pending else "unavailable"),
        "latest_status": latest.status if latest else "unavailable",
        "classification_basis": "composite",
        "policy_version": ABC_POLICY_VERSION,
        "composite_pending": composite_pending,
        "cutoff_date": str(run.cutoff_date) if run else None,
        "computed_at": run.completed_at.isoformat() if run and run.completed_at else None,
        "window_days": run.window_days if run else (settings.abc_window_days if settings else 90),
        "currency": run.currency if run else country.currency,
        "stale": bool(run and run.cutoff_date < today - timedelta(days=1)),
        "issues": sorted({str(issue).split(":", 1)[0] for issue in latest_composite.issues})
        if latest_composite and latest_composite.status in {"failed", "partial"} else [],
        "config_pending": config_pending,
    }
    return run, meta


def decorate_rows(actor, country, rows):
    run, meta = published_run(actor, country)
    all_rows = []
    for row in rows:
        all_rows.append(row)
        all_rows.extend(row.get("variants") or [])
    sku_ids = set()
    unmapped_ids = set()
    for row in all_rows:
        value = row.get("sku_id") or row.get("internal_sku_id") or row.get("internal_sku")
        if not isinstance(value, int) or isinstance(value, bool):
            value = row.get("id") if row.get("code") and not row.get("variants") else None
        if isinstance(value, int) and not isinstance(value, bool):
            sku_ids.add(value)
            if not row.get("spu_id"):
                unmapped_ids.add(value)
    sku_spus = dict(ProductSKU.objects.filter(tenant_id=actor.tenant_id, pk__in=unmapped_ids).values_list(
        "pk", "spu_id"
    )) if run else {}
    spu_ids = {row.get("spu_id") for row in all_rows if isinstance(row.get("spu_id"), int)} | set(sku_spus.values())
    for row in rows:
        if row.get("variants") and isinstance(row.get("id"), int):
            spu_ids.add(row["id"])
    entries = {}
    if run:
        query = InventoryABCEntry.objects.filter(run=run)
        query = query.filter(Q(entity_type="sku", entity_id__in=sku_ids) | Q(entity_type="spu", entity_id__in=spu_ids))
        entries = {(entry.entity_type, entry.entity_id): entry for entry in query}
    for row in all_rows:
        sku_id = row.get("sku_id") or row.get("internal_sku_id") or row.get("internal_sku")
        if not isinstance(sku_id, int):
            sku_id = row.get("id") if row.get("code") and not row.get("variants") else None
        spu_id = row.get("spu_id") or sku_spus.get(sku_id)
        if row.get("variants") and not spu_id and isinstance(row.get("id"), int):
            spu_id = row["id"]
        sku = entries.get(("sku", sku_id))
        spu = entries.get(("spu", spu_id))
        sku_evidence = sku.evidence if sku and isinstance(sku.evidence, dict) else {}
        spu_evidence = spu.evidence if spu and isinstance(spu.evidence, dict) else {}
        reference = meta["status"] == "partial"
        row["abc"] = {
            "classification_basis": meta["classification_basis"],
            "policy_version": meta["policy_version"],
            "sku_first_sale_date": str(sku.first_sale_date) if sku and sku.first_sale_date else None,
            "spu_first_sale_date": str(spu.first_sale_date) if spu and spu.first_sale_date else None,
            "observation_days": run.config.get("new_product_observation_days", 30) if run else 30,
            "stability_days": run.config.get("stability_days", 3) if run else 3,
            "run_id": meta["run_id"],
            "sku_grade": sku.grade if sku else "unavailable",
            "spu_grade": spu.grade if spu else "unavailable",
            "sku_candidate_grade": sku.candidate_grade if sku else "",
            "sku_candidate_streak": sku.candidate_streak if sku else 0,
            "spu_candidate_grade": spu.candidate_grade if spu else "",
            "spu_candidate_streak": spu.candidate_streak if spu else 0,
            "sku_reference_grade": sku_evidence.get("reference_grade", sku.candidate_grade) if sku and reference else "",
            "spu_reference_grade": spu_evidence.get("reference_grade", spu.candidate_grade) if spu and reference else "",
            "sku_evidence": sku_evidence,
            "spu_evidence": spu_evidence,
            "cutoff_date": meta["cutoff_date"],
            "computed_at": meta["computed_at"],
            "status": meta["status"],
            "stale": meta["stale"],
        }
    return meta


def filter_skus(actor, country, queryset, grade, grouped=False):
    if not grade:
        return queryset
    run, _ = published_run(actor, country)
    if not run:
        return queryset.none() if grade != "unavailable" else queryset
    grade_field = "candidate_grade" if run.status == "partial" and grade in {"A", "B", "C", "new"} else "grade"
    ids = InventoryABCEntry.objects.filter(run=run, entity_type="sku", **{grade_field: grade}).values_list("entity_id", flat=True)
    matched = queryset.filter(pk__in=ids)
    if grade == "unavailable":
        known = InventoryABCEntry.objects.filter(run=run, entity_type="sku").exclude(grade="unavailable").values_list("entity_id", flat=True)
        matched = queryset.exclude(pk__in=known)
    return queryset.filter(spu_id__in=matched.values("spu_id")) if grouped else matched
