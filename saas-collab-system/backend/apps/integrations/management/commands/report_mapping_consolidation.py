"""Report safe candidates and conflicts for legacy product mapping consolidation."""

from collections import defaultdict
import json

from django.core.management.base import BaseCommand, CommandError


REPORT_CATEGORIES = (
    "unmatched",
    "multiple_detail",
    "identity_conflict",
    "sku_conflict",
    "duplicate_mapping",
    "mapped_detail_sku_missing",
    "ready",
)


def _normalized(value):
    return str(value or "").strip().lower()


def _platform_values(detail):
    return {
        value
        for value in (
            _normalized(detail.platform.platform_type),
            _normalized(detail.platform.code),
        )
        if value
    }


def _mapping_store_id(mapping):
    return getattr(mapping.store_mapping, "store_id", None)


def _detail_key(*, tenant_id, platform, store_id, variant_id):
    return (
        tenant_id,
        _normalized(platform),
        store_id,
        str(variant_id or "").strip(),
    )


def _mapping_key(mapping):
    return _detail_key(
        tenant_id=mapping.tenant_id,
        platform=mapping.platform,
        store_id=_mapping_store_id(mapping),
        variant_id=mapping.platform_variant_id,
    )


def _record_identifier(mapping, *, candidate_detail_ids=None, detail=None):
    """Return reconciliation identifiers only; never include credential data."""

    return {
        "mapping_id": mapping.id,
        "tenant_id": mapping.tenant_id,
        "store_mapping_id": mapping.store_mapping_id,
        "store_id": _mapping_store_id(mapping),
        "platform": _normalized(mapping.platform),
        "platform_product_id": mapping.platform_product_id,
        "platform_variant_id": mapping.platform_variant_id,
        "platform_sku": mapping.platform_sku,
        "sku_id": mapping.sku_id,
        "status": mapping.status,
        "platform_detail_id": mapping.platform_detail_id,
        "candidate_detail_ids": list(candidate_detail_ids or []),
        "detail_sku_id": getattr(detail, "internal_sku_id", None),
    }


def _identity_and_sku_issues(mapping, detail):
    """Return actual consistency issues for a single candidate detail."""

    identity_issues = set()
    if detail is None:
        identity_issues.add("identity_conflict")
        return identity_issues

    if mapping.tenant_id != detail.tenant_id:
        identity_issues.add("identity_conflict")
    if _normalized(mapping.platform) not in _platform_values(detail):
        identity_issues.add("identity_conflict")
    if _mapping_store_id(mapping) != detail.store_id:
        identity_issues.add("identity_conflict")
    if str(mapping.platform_variant_id or "").strip() != str(detail.platform_variant_id or "").strip():
        identity_issues.add("identity_conflict")

    # A populated historical identity must agree with the canonical snapshot;
    # an empty snapshot field is incomplete data, but is not an invented
    # conflict.  The report keeps that distinction for manual reconciliation.
    if (
        mapping.platform_product_id
        and detail.platform_product_id
        and mapping.platform_product_id != detail.platform_product_id
    ):
        identity_issues.add("identity_conflict")
    if mapping.platform_sku and detail.platform_sku and mapping.platform_sku != detail.platform_sku:
        identity_issues.add("identity_conflict")

    # The migration contract is strict equality, including NULL: a one-sided
    # SKU is not an identity match and must never be reported as ready.
    if mapping.sku_id != detail.internal_sku_id:
        identity_issues.add("sku_conflict")

    # A mapped legacy decision is not safe to consolidate while either side of
    # the canonical SKU identity is missing.  A non-mapped row whose detail
    # has no SKU is also explicitly reported as incomplete rather than silently
    # treated as a safe link.
    if (
        detail.internal_sku_id is None
        and mapping.sku_id is not None
    ) or (
        mapping.status == "mapped"
        and (mapping.sku_id is None or detail.internal_sku_id is None)
    ):
        identity_issues.add("mapped_detail_sku_missing")
    return identity_issues


class Command(BaseCommand):
    help = "Report read-only platform product mapping consolidation candidates and conflicts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=None,
            help="Only report mappings and platform details belonging to this tenant.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Iterator batch size for the read-only scan (default: 500).",
        )

    def _mapping_queryset(self, MarketplaceProductMapping, tenant_id):
        queryset = MarketplaceProductMapping.objects.all()
        if tenant_id is not None:
            queryset = queryset.filter(tenant_id=tenant_id)
        return queryset.select_related(
            "store_mapping",
            "platform_detail",
            "platform_detail__platform",
        ).order_by("id")

    def _detail_index(self, PlatformProductDetail, tenant_id, batch_size):
        queryset = PlatformProductDetail.objects.select_related("platform").order_by("id")
        if tenant_id is not None:
            queryset = queryset.filter(tenant_id=tenant_id)
        by_key = defaultdict(dict)
        by_id = {}
        for detail in queryset.iterator(chunk_size=batch_size):
            by_id[detail.id] = detail
            key_base = {
                "tenant_id": detail.tenant_id,
                "store_id": detail.store_id,
                "variant_id": detail.platform_variant_id,
            }
            for platform in _platform_values(detail):
                by_key[_detail_key(platform=platform, **key_base)][detail.id] = detail
        return by_key, by_id

    @staticmethod
    def _matching_details(mapping, detail_index):
        return list(detail_index.get(_mapping_key(mapping), {}).values())

    def _duplicate_mapping_ids(self, mapping_queryset, detail_index, batch_size):
        detail_to_mapping_ids = defaultdict(list)
        for mapping in mapping_queryset.iterator(chunk_size=batch_size):
            if mapping.platform_detail_id:
                detail_to_mapping_ids[mapping.platform_detail_id].append(mapping.id)
                continue
            candidates = self._matching_details(mapping, detail_index)
            if len(candidates) == 1:
                detail_to_mapping_ids[candidates[0].id].append(mapping.id)

        duplicate_ids = set()
        for mapping_ids in detail_to_mapping_ids.values():
            if len(mapping_ids) > 1:
                duplicate_ids.update(mapping_ids)
        return duplicate_ids

    def handle(self, *args, **options):
        tenant_id = options.get("tenant_id")
        batch_size = options.get("batch_size")
        if tenant_id is not None and tenant_id <= 0:
            raise CommandError("--tenant-id must be a positive integer.")
        if not isinstance(batch_size, int) or batch_size <= 0:
            raise CommandError("--batch-size must be a positive integer.")

        from apps.integrations.models import MarketplaceProductMapping
        from apps.listings.models import PlatformProductDetail

        detail_index, detail_by_id = self._detail_index(PlatformProductDetail, tenant_id, batch_size)
        mapping_queryset = self._mapping_queryset(MarketplaceProductMapping, tenant_id)
        duplicate_mapping_ids = self._duplicate_mapping_ids(mapping_queryset, detail_index, batch_size)

        counts = {category: 0 for category in REPORT_CATEGORIES}
        counts["linked"] = 0
        counts["total"] = 0
        identifiers = {category: [] for category in (*REPORT_CATEGORIES, "linked")}
        items = []

        # The second iterator pass emits stable, human-checkable identifiers
        # after duplicate candidates have been calculated.  It still performs
        # no save, update, delete, locking, or credential access.
        for mapping in mapping_queryset.iterator(chunk_size=batch_size):
            counts["total"] += 1
            if mapping.platform_detail_id:
                detail = detail_by_id.get(mapping.platform_detail_id)
                candidate_details = [detail] if detail is not None else []
            else:
                candidate_details = self._matching_details(mapping, detail_index)
                detail = candidate_details[0] if len(candidate_details) == 1 else None

            issues = set()
            if not mapping.platform_detail_id and not candidate_details:
                issues.add("unmatched")
            elif not mapping.platform_detail_id and len(candidate_details) > 1:
                issues.add("multiple_detail")
            elif detail is not None:
                issues.update(_identity_and_sku_issues(mapping, detail))
            else:
                issues.add("identity_conflict")

            if mapping.id in duplicate_mapping_ids:
                issues.add("duplicate_mapping")

            if not mapping.platform_detail_id and len(candidate_details) == 1 and not issues:
                issues.add("ready")

            base = _record_identifier(
                mapping,
                candidate_detail_ids=[item.id for item in candidate_details],
                detail=detail,
            )
            if not issues and mapping.platform_detail_id:
                counts["linked"] += 1
                identifiers["linked"].append(base)
                continue

            if not issues:
                continue
            primary_category = next(
                category for category in (*REPORT_CATEGORIES, "linked") if category in issues
            )
            item = {
                **base,
                "category": primary_category,
                "categories": [category for category in REPORT_CATEGORIES if category in issues],
            }
            items.append(item)
            for category in REPORT_CATEGORIES:
                if category in issues:
                    counts[category] += 1
                    identifiers[category].append(base)

        report = {
            "command": "report_mapping_consolidation",
            "tenant_id": tenant_id,
            "counts": counts,
            "identifiers": identifiers,
            "items": items,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
