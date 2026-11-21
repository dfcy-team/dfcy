"""Fill only derived columns; preserve every original row, value and identifier.

The cutover controller must fence/drain legacy writers before this migration and
keep them fenced through 0015. No current configuration-only country fallback,
provider calls, snapshot rewriting, projection deletes or projection inserts.
"""
import hashlib
import json

from django.db import migrations, transaction
from django.db.models import Count, Q
from django.db.models.fields.json import KeyTextTransform

SUPPORTED_SITES = frozenset(("PH", "MY", "TH"))
BATCH_SIZE = 250
MAX_LEGACY_ROWS = 2_000_000
LEGACY_FIELDS = (
    "pk", "lookup_id", "tenant_id", "warehouse_id", "document",
    "warehouse_sku", "source_sku", "quantity", "shipped_at",
)


def reject(code):
    # Errors must never disclose a document, SKU, order or tenant identifier.
    raise RuntimeError("V518_OUTBOUND_" + code)


def derive_identity(document, warehouse_sku, source_sku, *, snapshot_site,
                    order_region, store_country, warehouse_country):
    identifiers = (document, warehouse_sku, source_sku)
    if any(not isinstance(v, str) or v != v.strip() or len(v) > 191 for v in identifiers):
        reject("NONCANONICAL_IDENTITY")
    if not document or not (warehouse_sku or source_sku):
        reject("EMPTY_IDENTITY")
    region = str(order_region or "").strip().upper()
    recorded_site = str(snapshot_site or "").strip().upper()
    if region not in SUPPORTED_SITES:
        reject("MISSING_PERSISTED_COUNTRY")
    # Missing old snapshot country may use the persisted SalesOrder.region fact.
    # The current store/warehouse values are corroboration, never the source.
    site = recorded_site or region
    if site not in SUPPORTED_SITES or site != region:
        reject("COUNTRY_CONFLICT")
    if any(str(v or "").strip().upper() != site for v in (store_country, warehouse_country)):
        reject("COUNTRY_RELATION_CONFLICT")
    identity = json.dumps([document, warehouse_sku, source_sku], ensure_ascii=False, separators=(",", ":"))
    return site, hashlib.sha256(document.encode("utf-8")).hexdigest(), hashlib.sha256(identity.encode("utf-8")).hexdigest()


def digest_row(hasher, row):
    values = list(row)
    values[-1] = values[-1].isoformat()
    hasher.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    hasher.update(b"\n")


def keyset_batches(queryset, upper_pk):
    """Bound mysqlclient's buffered result to one page, not the whole table."""
    last_pk = 0
    while last_pk < upper_pk:
        batch = list(queryset.filter(pk__gt=last_pk, pk__lte=upper_pk).order_by("pk")[:BATCH_SIZE])
        if not batch:
            break
        yield batch
        last_pk = batch[-1][0]


def fill_identity(apps, schema_editor):
    Line = apps.get_model("sales_management", "WarehouseOutboundLine")
    alias = schema_editor.connection.alias
    lines = Line.objects.using(alias)
    # DML is one transaction even on MySQL (DDL phases are separate migrations).
    with transaction.atomic(using=alias):
        count = lines.count()
        if count > MAX_LEGACY_ROWS:
            reject("RESOURCE_BUDGET_REQUIRES_REVIEW")
        upper_pk = lines.select_for_update().order_by("-pk").values_list("pk", flat=True).first() or 0
        before = hashlib.sha256()
        pending = []
        seen = 0
        selected = lines.select_for_update().annotate(
            snapshot_site=KeyTextTransform("site_code", "lookup__snapshot"),
        ).order_by("pk").values_list(
            *LEGACY_FIELDS,
            "lookup__order__tenant_id", "lookup__order__store__tenant_id",
            "warehouse__tenant_id", "lookup__warehouse_id",
            "lookup__order__region", "lookup__order__store__country_code",
            "warehouse__country_code", "snapshot_site",
            "site_code", "document_key", "identity_key",
        )
        for row in (row for batch in keyset_batches(selected, upper_pk) for row in batch):
            pk, lookup_id, tenant_id, warehouse_id, document, warehouse_sku, source_sku, quantity, shipped_at = row[:9]
            order_tenant, store_tenant, warehouse_tenant, lookup_warehouse = row[9:13]
            order_region, store_country, warehouse_country, snapshot_site = row[13:17]
            if tenant_id != order_tenant or tenant_id != store_tenant or tenant_id != warehouse_tenant or warehouse_id != lookup_warehouse:
                reject("RELATION_CONFLICT")
            if not isinstance(quantity, int) or quantity <= 0 or quantity > 2**63 - 1:
                reject("INVALID_QUANTITY")
            if shipped_at is None:
                reject("MISSING_SHIPPED_AT")
            site, doc_key, identity_key = derive_identity(
                document, warehouse_sku, source_sku, snapshot_site=snapshot_site,
                order_region=order_region, store_country=store_country, warehouse_country=warehouse_country,
            )
            expected = (site, doc_key, identity_key)
            if any(old is not None and old != new for old, new in zip(row[17:20], expected)):
                reject("EXISTING_DERIVED_VALUE_CONFLICT")
            digest_row(before, row[:9])
            seen += 1
            if row[17:20] != expected:
                pending.append(Line(pk=pk, site_code=site, document_key=doc_key, identity_key=identity_key))
            if len(pending) >= BATCH_SIZE:
                lines.bulk_update(pending, ["site_code", "document_key", "identity_key"], batch_size=BATCH_SIZE)
                pending.clear()
        if pending:
            lines.bulk_update(pending, ["site_code", "document_key", "identity_key"], batch_size=BATCH_SIZE)
        final_pk = lines.select_for_update().order_by("-pk").values_list("pk", flat=True).first() or 0
        if seen != count or lines.count() != count or final_pk != upper_pk:
            reject("CONCURRENT_ROW_COUNT_CHANGE")
        if lines.filter(Q(site_code__isnull=True) | Q(document_key__isnull=True) | Q(identity_key__isnull=True)).exists():
            reject("INCOMPLETE_DERIVED_VALUES")
        if lines.values("lookup_id", "identity_key").annotate(n=Count("pk")).filter(n__gt=1).exists():
            reject("IDENTITY_COLLISION")
        after = hashlib.sha256()
        for row in (row for batch in keyset_batches(lines.values_list(*LEGACY_FIELDS), upper_pk) for row in batch):
            digest_row(after, row)
        if before.digest() != after.digest():
            reject("LEGACY_VALUE_OR_ID_CHANGED")


class Migration(migrations.Migration):
    dependencies = [("sales_management", "0013_expand_outbound_identity")]
    operations = [migrations.RunPython(fill_identity, migrations.RunPython.noop, atomic=True)]
