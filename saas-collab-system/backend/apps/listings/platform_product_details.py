"""Import and upsert helpers for platform product detail snapshots."""
import csv
import io
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime
from xml.etree import ElementTree

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.masterdata.models import CountrySiteMaster, PlatformMaster, StoreMaster
from apps.products.models import ProductLegacyItem, ProductSKU

from .models import PlatformProductDetail


HEADER_ALIASES = {
    "主商品ID": "platform_product_id", "主商品id": "platform_product_id", "商品ID": "platform_product_id", "商品id": "platform_product_id",
    "商品名称": "title", "产品名称": "title", "标题": "title",
    "变种": "variant", "变体": "variant", "变种ID": "platform_variant_id", "变体ID": "platform_variant_id",
    "SKU": "source_old_sku_code", "旧SKU": "source_old_sku_code", "旧SKU编码": "source_old_sku_code", "新SKU": "new_sku_code", "新SKU编码": "new_sku_code", "平台SKU": "platform_sku", "平台SKU编码": "platform_sku", "创建时间": "platform_created_at", "最后更新时间": "platform_updated_at",
    "SKU前缀": "sku_prefix", "店铺简写": "shop_abbr", "店铺": "shop_abbr", "店铺名称": "store_name",
    "销售状态": "sales_status", "店铺负责人": "owner", "负责人": "owner", "店铺组长": "leader", "组长": "leader",
    "L1": "category_l1", "L2": "category_l2", "L3": "category_l3", "L1类目": "category_l1", "L2类目": "category_l2", "L3类目": "category_l3",
    "平台": "platform", "平台商品ID": "platform_product_id", "国家代码": "country_code", "country_code": "country_code", "country code": "country_code", "站点": "site", "site_code": "site", "site code": "site",
}

# Canonical headers emitted by the downloadable template.  Keep the legacy
# aliases above so imports exported by the previous UI remain compatible.
HEADER_ALIASES.update({
    "平台": "platform", "店铺": "store_name", "店铺编码": "store_code", "国家代码": "country_code", "country_code": "country_code", "country code": "country_code", "站点": "site", "site_code": "site", "site code": "site",
    "平台商品ID": "platform_product_id", "商品ID": "platform_product_id", "变体ID": "platform_variant_id",
    "平台SKU": "platform_sku", "旧SKU编码": "source_old_sku_code", "旧SKU": "source_old_sku_code", "新SKU编码": "new_sku_code", "新SKU": "new_sku_code",
    "new_sku_code": "new_sku_code", "new sku code": "new_sku_code",
    # English field names are accepted alongside the downloadable template's
    # localized headers.  ``_key`` removes separators when resolving aliases.
    "platform": "platform", "store": "store", "store_code": "store_code", "store_name": "store_name",
    "platform_product_id": "platform_product_id", "platform_variant_id": "platform_variant_id", "platform_sku": "platform_sku",
    "variant_id": "platform_variant_id", "variant id": "platform_variant_id", "platform variant id": "platform_variant_id",
    "product_id": "platform_product_id", "product id": "platform_product_id", "platform product id": "platform_product_id",
    "source_old_sku_code": "source_old_sku_code", "title": "title", "variant": "variant",
    "sku_prefix": "sku_prefix", "shop_abbr": "shop_abbr", "sales_status": "sales_status",
    "owner": "owner", "leader": "leader", "category_l1": "category_l1", "category_l2": "category_l2", "category_l3": "category_l3",
    "platform_created_at": "platform_created_at", "platform_updated_at": "platform_updated_at",
    "标题": "title", "商品名称": "title", "变体": "variant", "变种": "variant",
    "L1类目": "category_l1", "L2类目": "category_l2", "L3类目": "category_l3",
    "SKU前缀": "sku_prefix", "店铺简称": "shop_abbr", "销售状态": "sales_status",
    "负责人": "owner", "店铺负责人": "owner", "组长": "leader", "店铺组长": "leader",
    "平台创建时间": "platform_created_at", "平台更新时间": "platform_updated_at", "最后更新时间": "platform_updated_at",
})


# Import writes are deliberately bounded independently from the parser.  A
# single call to Django's ``bulk_update`` builds every CASE expression for the
# supplied object list before sending any SQL.  Keeping the work list small
# prevents a large (tens-of-thousands row) re-upload from retaining a huge AST
# in a Gunicorn worker while still allowing each SQL statement to be efficient.
IMPORT_WRITE_CHUNK_SIZE = 1000
IMPORT_CREATE_BATCH_SIZE = 1000
IMPORT_UPDATE_BATCH_SIZE = 100
IMPORT_UPDATE_WORK_CHUNK_SIZE = 500
IMPORT_EXISTING_QUERY_CHUNK_SIZE = 2000
UNMATCHED_SAMPLE_LIMIT = 100

# The key columns are already constrained by the lookup and must not be
# rewritten.  All remaining fields are values supplied by an import and are
# compared before an update so an idempotent re-upload does not issue writes.
IMPORT_UPDATE_FIELDS = (
    "site",
    "platform_product_id",
    "platform_sku",
    "source_old_sku_code",
    "internal_sku",
    "title",
    "variant",
    "category_l1",
    "category_l2",
    "category_l3",
    "sku_prefix",
    "shop_abbr",
    "sales_status",
    "owner",
    "leader",
    "platform_created_at",
    "platform_updated_at",
    "source",
)


def _text(value):
    return "" if value is None else str(value).strip()


def _clean_sku(value):
    """Normalize an imported SKU for display while preserving its case."""
    value = "" if value is None else str(value)
    value = unicodedata.normalize("NFKC", value)
    value = "".join(char for char in value if unicodedata.category(char) != "Cf")
    return value.strip()


def _sku_key(value):
    """Build a normalized, case-insensitive key for SKU matching."""
    return _clean_sku(value).casefold()


def _key(value):
    return re.sub(r"[\s_\-（）()]+", "", _text(value)).casefold()


def _parse_datetime(value):
    value = _text(value)
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.fromisoformat(value) if fmt is None else datetime.strptime(value, fmt)
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed
        except (ValueError, TypeError):
            continue
    raise ValueError(f"无法解析时间: {value}")


def _xlsx_rows(raw):
    """Read basic XLSX worksheets without adding a binary dependency."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            shared = ["".join(node.itertext()) for node in root.findall("x:si", ns)]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", rel_ns)}
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        for sheet in workbook.findall("x:sheets/x:sheet", ns):
            target = rel_map.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "")
            path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            if path not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(path))
            rows = []
            for row in root.findall(".//x:sheetData/x:row", ns):
                cells = {}
                for cell in row.findall("x:c", ns):
                    ref = cell.attrib.get("r", "A1")
                    col = re.match(r"[A-Z]+", ref).group(0)
                    value = cell.find("x:v", ns)
                    text = "" if value is None else value.text or ""
                    if cell.attrib.get("t") == "s" and text.isdigit() and int(text) < len(shared):
                        text = shared[int(text)]
                    inline = cell.find("x:is", ns)
                    if inline is not None:
                        text = "".join(inline.itertext())
                    cells[col] = text
                rows.append(cells)
            if rows:
                columns = sorted({c for row in rows for c in row}, key=lambda c: (len(c), c))
                yield _text(sheet.attrib.get("name")), [[row.get(c, "") for c in columns] for row in rows]


def parse_import_rows(raw, filename="", platform_hint=""):
    if filename.lower().endswith(".xlsx") or raw[:2] == b"PK":
        for sheet_name, rows in _xlsx_rows(raw):
            if not rows:
                continue
            yield sheet_name, _map_rows(rows, platform_hint or sheet_name)
        return
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if rows:
        yield "", _map_rows(rows, platform_hint)


def _map_rows(rows, platform_hint=""):
    headers = rows[0]
    mapped_headers = []
    for header in headers:
        normalized = _key(header)
        mapped_headers.append(next((value for key, value in HEADER_ALIASES.items() if _key(key) == normalized), normalized))
    result = []
    for row in rows[1:]:
        if not any(_text(value) for value in row):
            continue
        item = {mapped_headers[i]: _text(row[i]) if i < len(row) else "" for i in range(len(mapped_headers))}
        if platform_hint and not item.get("platform"):
            item["platform"] = platform_hint
        result.append(item)
    return result


def _resolve_platform(tenant, value, cache=None):
    value = _text(value)
    if not value:
        raise ValueError("缺少平台")
    if cache is not None:
        platform = cache.get(value.casefold())
        if platform:
            return platform
        raise ValueError(f"平台不存在: {value}")
    return PlatformMaster.objects.filter(tenant=tenant).filter(code__iexact=value).first() or PlatformMaster.objects.filter(tenant=tenant, name__iexact=value).first() or PlatformMaster.objects.filter(tenant=tenant, platform_type__iexact=value).first() or (_ for _ in ()).throw(ValueError(f"平台不存在: {value}"))


def _resolve_store(tenant, platform, row, cache=None):
    values = [_text(row.get("shop_abbr")), _text(row.get("store_name")), _text(row.get("store")), _text(row.get("store_code"))]
    values = [value for value in values if value]
    for value in values:
        if cache is not None:
            store = cache.get((platform.pk, value.casefold()))
            if store:
                return store
            continue
        store = StoreMaster.objects.filter(tenant=tenant, platform=platform).filter(code__iexact=value).first() or StoreMaster.objects.filter(tenant=tenant, platform=platform, name__iexact=value).first()
        if store:
            return store
    raise ValueError(f"店铺不存在或不属于平台: {values[0] if values else ''}")


def _cache_candidates(cache, key):
    """Read a cache entry while accepting both old and list-valued caches."""
    if cache is None:
        return []
    def as_list(candidates):
        if candidates is None:
            return []
        if isinstance(candidates, (list, tuple, set)):
            return list(candidates)
        return [candidates]

    # The importer builds normalized caches, so the overwhelmingly common
    # path is O(1) per row.  Only scan keys when handling a legacy exact-code
    # cache that does not contain the normalized key directly.
    if key in cache:
        return as_list(cache[key])

    if getattr(cache, "normalized_keys", False):
        return []

    matches = []
    # Cache keys created by the importer are already normalized.  Also scan
    # keys for direct callers that still provide the previous exact-code map,
    # so their case/NFKC variants receive the same matching behavior.
    for cache_key, candidates in cache.items():
        if cache_key != key and _sku_key(cache_key) != key:
            continue
        matches.extend(as_list(candidates))
    return matches


def _unique_skus(candidates):
    """Deduplicate SKU model instances by primary key, preserving order."""
    unique = {}
    for candidate in candidates:
        if candidate is not None:
            unique.setdefault(candidate.pk, candidate)
    return list(unique.values())


class _NormalizedSKUCache(dict):
    """Marker type for importer caches whose keys are already normalized."""

    normalized_keys = True


def _resolve_sku(tenant, row, new_skus=None, legacy_skus=None):
    # Clean first, then use casefolded keys for both cache and DB paths.  The
    # cleaned old value is also returned to the caller for persistence.
    new_value = _clean_sku(row.get("new_sku_code"))
    value = _clean_sku(row.get("source_old_sku_code"))
    new_key = _sku_key(new_value)
    old_key = _sku_key(value)
    if new_value:
        if new_skus is not None:
            candidates = _unique_skus(_cache_candidates(new_skus, new_key))
        else:
            candidates = _unique_skus(
                sku for sku in ProductSKU.objects.filter(tenant=tenant)
                if _sku_key(sku.sku_code) == new_key
            )
        if len(candidates) > 1:
            raise ValueError(f"新 SKU 匹配多个内部 SKU: {new_value}")
        if candidates:
            return candidates[0]
        raise ValueError(f"新 SKU 编码不存在或不属于当前租户: {new_value}")
    if not value:
        raise ValueError("旧 SKU 编码和新 SKU 编码必须至少填写一个")
    if legacy_skus is not None:
        candidates = _unique_skus(_cache_candidates(legacy_skus, old_key))
    else:
        legacy_items = ProductLegacyItem.objects.filter(tenant=tenant).select_related("generated_sku")
        candidates = [item.generated_sku for item in legacy_items
                      if item.generated_sku_id and _sku_key(item.legacy_sku_code) == old_key]
        candidates += [sku for sku in ProductSKU.objects.filter(tenant=tenant)
                       if _sku_key(sku.legacy_sku_code) == old_key]
        candidates = _unique_skus(candidates)
    if len(candidates) > 1:
        raise ValueError(f"旧 SKU 匹配多个内部 SKU: {value}")
    if candidates:
        return candidates[0]
    raise ValueError(f"旧 SKU 不存在或尚未生成新 SKU: {value}")


def _resolve_site(tenant, platform, store, row, sites=None):
    # ``国家代码`` is the canonical input.  Keep accepting the old ``站点``
    # header/value (site code or name) by resolving it inside the store's
    # country, while every selected record is still constrained by
    # CountrySiteMaster.country_code.
    country_code = _text(row.get("country_code")).upper()
    legacy_site = _text(row.get("site"))
    store_country = _text(store.country_code).upper()
    if country_code and country_code.casefold() != store_country.casefold():
        raise ValueError("国家代码与店铺国家不一致")
    country_code = country_code or store_country
    queryset = CountrySiteMaster.objects.filter(tenant=tenant, country_code__iexact=country_code) if sites is None else [item for item in sites if _text(item.country_code).casefold() == country_code.casefold()]
    if legacy_site:
        if sites is None:
            site = queryset.filter(code__iexact=legacy_site).first() or queryset.filter(name__iexact=legacy_site).first()
        else:
            site = next((item for item in queryset if _text(item.code).casefold() == legacy_site.casefold() or _text(item.name).casefold() == legacy_site.casefold()), None)
        if not site and not country_code:
            site = queryset.first() if sites is None else next(iter(queryset), None)
        if not site:
            # A legacy value may itself have been a country code.  This keeps
            # old exports useful while retaining country_code as the match key.
            site = (queryset.first() if sites is None else next(iter(queryset), None)) if legacy_site.casefold() == country_code.casefold() else None
        if not site:
            raise ValueError(f"国家代码不存在: {country_code or legacy_site}")
    else:
        if sites is None:
            site = queryset.filter(platform__iexact=platform.code).first() or queryset.filter(platform__iexact=platform.platform_type).first() or queryset.first()
        else:
            site = next((item for item in queryset if _text(item.platform).casefold() in {platform.code.casefold(), platform.platform_type.casefold()}), None) or next(iter(queryset), None)
    if site and site.platform and site.platform.casefold() not in {platform.code.casefold(), platform.name.casefold(), platform.platform_type.casefold()}:
        raise ValueError("国家信息所属平台与平台商品不一致")
    return site


def _chunks(items, size):
    """Yield bounded list slices without retaining an unbounded work batch."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _existing_for_plans(tenant, plans):
    """Load only destination rows addressed by one write chunk.

    The old importer selected every detail row for the tenant before deciding
    which records to update.  Apart from needless I/O, that made the Python
    object graph scale with the whole catalogue.  Grouping by the unique
    platform/store pair lets the database use the composite index and limits
    the variant ``IN`` list to a safe size for SQLite and MySQL alike.
    """
    grouped = defaultdict(set)
    for values in plans:
        grouped[(values["platform"].pk, values["store"].pk)].add(values["platform_variant_id"])

    # SQLite builds have a finite bound-parameter limit.  MySQL reports no
    # limit here, so the larger default is retained for production imports.
    query_chunk_size = IMPORT_EXISTING_QUERY_CHUNK_SIZE
    max_query_params = getattr(connection.features, "max_query_params", None)
    if max_query_params:
        query_chunk_size = min(query_chunk_size, max(1, max_query_params - 3))

    fields = [
        "platform",
        "store",
        "platform_variant_id",
        *IMPORT_UPDATE_FIELDS,
    ]
    existing = {}
    for (platform_id, store_id), variants in grouped.items():
        for variant_chunk in _chunks(list(variants), query_chunk_size):
            queryset = PlatformProductDetail.objects.filter(
                tenant_id=tenant.pk,
                platform_id=platform_id,
                store_id=store_id,
                platform_variant_id__in=variant_chunk,
            ).order_by().only(*fields)
            for item in queryset:
                existing[(item.platform_id, item.store_id, item.platform_variant_id)] = item
    return existing


def _same_import_value(instance, field_name, value):
    """Compare model/FK values without forcing deferred related queries."""
    if field_name in {"site", "internal_sku"}:
        expected_id = value.pk if value is not None else None
        return getattr(instance, f"{field_name}_id") == expected_id
    return getattr(instance, field_name) == value


def _bulk_update_import_chunks(update_groups):
    """Flush changed rows in bounded CASE statements.

    Django's ``bulk_update`` materializes all batches' CASE trees before it
    executes the first query.  Calling it per work chunk bounds that retained
    tree; the smaller batch size also avoids oversized MySQL statements.
    """
    for changed_fields, instances in update_groups.items():
        fields = [*changed_fields, "updated_at"]
        for update_chunk in _chunks(instances, IMPORT_UPDATE_WORK_CHUNK_SIZE):
            PlatformProductDetail.objects.bulk_update(
                update_chunk,
                fields,
                batch_size=IMPORT_UPDATE_BATCH_SIZE,
            )


def import_platform_product_details(*, tenant, raw, filename="", platform_hint="", dry_run=False, actor=None):
    errors, created, updated, unchanged = [], 0, 0, 0
    rows_seen = 0
    plans = []
    platforms = list(PlatformMaster.objects.filter(tenant=tenant))
    platform_cache = {value.casefold(): item for item in platforms for value in (item.code, item.name, item.platform_type) if value}
    stores = list(StoreMaster.objects.filter(tenant=tenant))
    store_cache = {(item.platform_id, value.casefold()): item for item in stores for value in (item.code, item.name) if value}
    sites = list(CountrySiteMaster.objects.filter(tenant=tenant))
    sku_rows = list(ProductSKU.objects.filter(tenant=tenant).only("id", "sku_code", "legacy_sku_code", "tenant_id", "spu_id"))
    # Index by normalized keys and retain every candidate so a case/NFKC
    # collision is reported as ambiguous instead of whichever row was last.
    new_sku_index = {}
    for item in sku_rows:
        new_sku_index.setdefault(_sku_key(item.sku_code), {})[item.pk] = item
    new_skus = _NormalizedSKUCache({key: list(items.values()) for key, items in new_sku_index.items()})
    legacy_skus = {}
    for item in sku_rows:
        if item.legacy_sku_code:
            legacy_skus.setdefault(_sku_key(item.legacy_sku_code), {})[item.pk] = item
    for item in ProductLegacyItem.objects.filter(tenant=tenant, generated_sku__isnull=False).select_related("generated_sku"):
        legacy_skus.setdefault(_sku_key(item.legacy_sku_code), {})[item.generated_sku_id] = item.generated_sku
    legacy_skus = _NormalizedSKUCache({code: list(items.values()) for code, items in legacy_skus.items()})
    for sheet_name, rows in parse_import_rows(raw, filename, platform_hint):
        for row_index, row in enumerate(rows, start=2):
            rows_seen += 1
            line = row_index
            try:
                platform = _resolve_platform(tenant, row.get("platform") or sheet_name.replace("商品明细", ""), platform_cache)
                store = _resolve_store(tenant, platform, row, store_cache)
                variant_id = _text(row.get("platform_variant_id"))
                if not variant_id:
                    raise ValueError("缺少变种ID")
                site = _resolve_site(tenant, platform, store, row, sites)
                sku = _resolve_sku(tenant, row, new_skus, legacy_skus)
                values = {
                    "tenant": tenant, "platform": platform, "store": store, "site": site,
                    "platform_product_id": _text(row.get("platform_product_id")), "platform_variant_id": variant_id,
                    "platform_sku": _text(row.get("platform_sku")), "source_old_sku_code": _clean_sku(row.get("source_old_sku_code")), "internal_sku": sku,
                    "title": _text(row.get("title")), "variant": _text(row.get("variant")),
                    "category_l1": _text(row.get("category_l1")), "category_l2": _text(row.get("category_l2")), "category_l3": _text(row.get("category_l3")),
                    "sku_prefix": _text(row.get("sku_prefix")), "shop_abbr": _text(row.get("shop_abbr")), "sales_status": _text(row.get("sales_status")),
                    "owner": _text(row.get("owner")), "leader": _text(row.get("leader")), "source": "import",
                    "platform_created_at": _parse_datetime(row.get("platform_created_at")), "platform_updated_at": _parse_datetime(row.get("platform_updated_at")),
                }
                plans.append(values)
            except (ValueError, TypeError, KeyError) as exc:
                errors.append({"row": line, "sheet": sheet_name, "message": str(exc)})
    # Keep valid rows transactional and idempotent even when another row in
    # the same upload is invalid.  Invalid rows remain in ``errors`` and are
    # reported to the caller without rolling back valid plans.
    if not dry_run and plans:
        # A platform/store/variant key is unique in the destination.  Keep
        # the last valid occurrence in a file so a future duplicate export
        # cannot make ``bulk_create`` fail on a uniqueness conflict.
        unique_plans = {}
        for values in plans:
            key = (values["platform"].pk, values["store"].pk, values["platform_variant_id"])
            unique_plans[key] = values
        plans = list(unique_plans.values())

        # Process destination lookups and writes in bounded chunks.  This both
        # avoids selecting unrelated tenant rows and bounds Django's CASE AST
        # retention during bulk updates.
        for plan_chunk in _chunks(plans, IMPORT_WRITE_CHUNK_SIZE):
            existing = _existing_for_plans(tenant, plan_chunk)
            to_create = []
            update_groups = defaultdict(list)
            now = timezone.now()
            for values in plan_chunk:
                key = (values["platform"].pk, values["store"].pk, values["platform_variant_id"])
                instance = existing.get(key)
                if instance is None:
                    to_create.append(PlatformProductDetail(**values))
                    created += 1
                    continue

                changed_fields = []
                for name in IMPORT_UPDATE_FIELDS:
                    value = values[name]
                    if not _same_import_value(instance, name, value):
                        setattr(instance, name, value)
                        changed_fields.append(name)
                if not changed_fields:
                    unchanged += 1
                    continue
                instance.updated_at = now
                update_groups[tuple(changed_fields)].append(instance)
                updated += 1

            with transaction.atomic():
                if to_create:
                    PlatformProductDetail.objects.bulk_create(
                        to_create,
                        batch_size=IMPORT_CREATE_BATCH_SIZE,
                    )
                if update_groups:
                    _bulk_update_import_chunks(update_groups)
    return {
        "dry_run": dry_run,
        "total": rows_seen,
        "valid": len(plans),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
        "skipped": len(errors),
        "partial_success": bool(errors and plans),
    }


def import_platform_product_ids(*, tenant, raw, filename="", dry_run=False):
    """Update platform product IDs by existing tenant-scoped variant IDs."""

    errors = []
    rows_seen = 0
    candidates = []
    for sheet_name, rows in parse_import_rows(raw, filename):
        for row_index, row in enumerate(rows, start=2):
            rows_seen += 1
            variant_id = _text(row.get("platform_variant_id"))
            product_id = _text(row.get("platform_product_id"))
            if not variant_id:
                errors.append({"row": row_index, "sheet": sheet_name, "code": "missing_variant_id", "message": "缺少变体ID。"})
                continue
            if not product_id:
                errors.append({"row": row_index, "sheet": sheet_name, "code": "missing_product_id", "message": "缺少平台商品ID。"})
                continue
            candidates.append({"row": row_index, "sheet": sheet_name, "variant_id": variant_id, "product_id": product_id})

    by_variant = defaultdict(list)
    for item in candidates:
        by_variant[item["variant_id"]].append(item)
    groups = []
    for variant_id, group in by_variant.items():
        product_ids = {item["product_id"] for item in group}
        if len(product_ids) > 1:
            for item in group:
                errors.append({
                    "row": item["row"],
                    "sheet": item["sheet"],
                    "code": "duplicate_variant_product_id",
                    "message": "同一变体ID在文件中对应多个平台商品ID，已跳过。",
                })
            continue
        groups.append({"variant_id": variant_id, "product_id": group[0]["product_id"], "rows": group})

    updated = 0
    unchanged = 0
    unmatched = 0
    unmatched_unique_count = 0
    unmatched_variant_seen = set()
    unmatched_sample = []
    ambiguous = 0
    changed_items = []
    with transaction.atomic():
        for group_chunk in _chunks(groups, IMPORT_EXISTING_QUERY_CHUNK_SIZE):
            variant_ids = [group["variant_id"] for group in group_chunk]
            queryset = PlatformProductDetail.objects.filter(
                tenant=tenant,
                platform_variant_id__in=variant_ids,
            )
            if not dry_run:
                queryset = queryset.select_for_update()
            matches_by_variant = defaultdict(list)
            for item in queryset:
                matches_by_variant[item.platform_variant_id].append(item)

            for group in group_chunk:
                rows = group["rows"]
                matches = matches_by_variant.get(group["variant_id"], [])
                if not matches:
                    unmatched += len(rows)
                    if group["variant_id"] not in unmatched_variant_seen:
                        unmatched_variant_seen.add(group["variant_id"])
                        unmatched_unique_count += 1
                        if len(unmatched_sample) < UNMATCHED_SAMPLE_LIMIT:
                            unmatched_sample.append(group["variant_id"])
                    continue
                if len(matches) > 1:
                    ambiguous += len(rows)
                    for row in rows:
                        errors.append({
                            "row": row["row"],
                            "sheet": row["sheet"],
                            "code": "ambiguous_variant_id",
                            "message": "当前租户内该变体ID对应多个平台/店铺记录，无法确定更新对象。",
                        })
                    continue
                item = matches[0]
                if item.platform_product_id == group["product_id"]:
                    unchanged += len(rows)
                    continue
                item.platform_product_id = group["product_id"]
                item.updated_at = timezone.now()
                if not dry_run:
                    changed_items.append(item)
                updated += 1
                unchanged += max(0, len(rows) - 1)

        if not dry_run and changed_items:
            PlatformProductDetail.objects.bulk_update(
                changed_items,
                ["platform_product_id", "updated_at"],
                batch_size=IMPORT_UPDATE_BATCH_SIZE,
            )

    return {
        "dry_run": dry_run,
        "total": rows_seen,
        "valid": sum(len(group["rows"]) for group in groups),
        "updated": updated,
        "unchanged": unchanged,
        "unmatched": unmatched,
        "unmatched_unique": unmatched_unique_count,
        "unmatched_sample": unmatched_sample,
        "unmatched_sample_limit": UNMATCHED_SAMPLE_LIMIT,
        "unmatched_remaining": max(0, unmatched_unique_count - len(unmatched_sample)),
        "ambiguous": ambiguous,
        "errors": errors,
        "skipped": max(0, rows_seen - updated - unchanged),
        "partial_success": bool((updated or unchanged) and (rows_seen - updated - unchanged)),
    }
