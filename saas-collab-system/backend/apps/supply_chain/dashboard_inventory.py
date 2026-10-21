"""Third-party WMS on-hand summary for the supply-chain cockpit."""
from datetime import timedelta

from django.db.models import BooleanField, Count, F, Func, Q, Sum, Value
from django.utils import timezone

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import SyncRun
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management.scopes import filter_inventory_queryset


INVENTORY_PERMISSION = "sales_management.view"
INVENTORY_RESOURCE = "commerce.inventory"
QUANTITY_FIELD = "available_qty"
FRESHNESS = timedelta(hours=24)


class JSONArrayHasValue(Func):
    """Exact JSON array membership across the supported database engines."""
    output_field = BooleanField()

    def __init__(self, expression, value):
        super().__init__(expression, Value(value))

    def as_sqlite(self, compiler, connection, **extra_context):
        expression, expression_params = compiler.compile(self.source_expressions[0])
        value, value_params = compiler.compile(self.source_expressions[1])
        return (f"EXISTS (SELECT 1 FROM json_each({expression}) WHERE json_each.value = {value})",
            (*expression_params, *value_params))

    def as_mysql(self, compiler, connection, **extra_context):
        expression, expression_params = compiler.compile(self.source_expressions[0])
        value, value_params = compiler.compile(self.source_expressions[1])
        return f"JSON_CONTAINS({expression}, JSON_QUOTE({value}))", (*expression_params, *value_params)

    def as_postgresql(self, compiler, connection, **extra_context):
        expression, expression_params = compiler.compile(self.source_expressions[0])
        value, value_params = compiler.compile(self.source_expressions[1])
        return f"({expression} ? {value})", (*expression_params, *value_params)


def inventory_data(actor, scoped, country_id=None):
    """Return third-party available stock by cockpit country.

    Quantity is deliberately unknown unless every latest physical, mapped SKU
    identity for that country has a successful, fresh snapshot containing the
    available quantity field. This prevents partial/failed data from looking
    like a reliable zero.
    """
    countries = scoped[0]
    base = {
        "totals": {"available_quantity": None, "snapshots": 0, "unknown": 0,
                   "failed": 0, "stale": 0, "unmapped": 0, "country_conflicts": 0},
        "countries": [],
        "status": "unavailable",
        "notice": "普通商品可用数量来自第三方 WMS 最新快照（排除虚拟及组合商品）；缺失、失败、过期或未映射数据不按零计，货值待统一成本口径。",
    }
    permission_cache = getattr(actor, "_permission_resolution_cache", None)
    if (not check_user_permission(actor, INVENTORY_PERMISSION, cache=permission_cache)
            or not get_permission_data_scopes(actor, INVENTORY_PERMISSION,
                resource_code=INVENTORY_RESOURCE, cache=permission_cache)):
        return base

    country_rows = list(countries.order_by("country_code", "pk"))
    if country_id is not None:
        country_rows = [row for row in country_rows if row.pk == country_id]
    country_by_code = {row.country_code.upper(): row for row in country_rows}
    rows = {row.pk: {"country_id": row.pk, "country_code": row.country_code,
        "country_name": row.name, "available_quantity": None, "snapshots": 0,
        "unknown": 0, "failed": 0, "stale": 0, "unmapped": 0,
        "country_conflicts": 0, "status": "unavailable"} for row in country_rows}
    if not country_rows:
        base["countries"] = []
        return base

    codes = list(country_by_code)
    snapshots = InventorySnapshot.objects.filter(
        tenant_id=actor.tenant_id,
        source_run__sync_job__integration_config__platform="jifeng_wms",
        source_run__sync_job__resource_type="inventory_snapshot",
    ).filter(Q(site_code__in=codes) | Q(warehouse__country_code__in=codes)).order_by()
    # Rank the complete tenant identity first. Scope, failure, mapping, virtual,
    # and freshness filters must not reveal an older valid snapshot.
    from apps.sales_management.views import _inventory_latest
    latest = _inventory_latest(snapshots)
    latest = filter_inventory_queryset(actor, INVENTORY_PERMISSION, latest,
        permission_cache).exclude(internal_sku__inventory_type="virtual").exclude(internal_sku__spu__product_type="bundle")
    latest = latest.filter(Q(site_code__in=codes) | Q(warehouse__country_code__in=codes))

    # A country/site mismatch is surfaced for reconciliation and never assigned
    # to either country. Quantities only include successful, fresh, mapped rows
    # with an explicitly provided available_qty.
    latest = latest.annotate(has_available_quantity=JSONArrayHasValue(F("provided_quantity_fields"), QUANTITY_FIELD))
    now = timezone.now()
    grouped = latest.values("site_code", "warehouse__country_code").annotate(
        snapshots=Count("pk"),
        failed=Count("pk", filter=(~Q(source_run__status=SyncRun.Status.SUCCESS) | Q(source_run__failed_count__gt=0))),
        stale=Count("pk", filter=Q(snapshot_at_utc__lt=now - FRESHNESS)),
        unmapped=Count("pk", filter=Q(internal_sku_id__isnull=True)),
        country_conflicts=Count("pk", filter=~Q(site_code=F("warehouse__country_code"))),
        missing=Count("pk", filter=Q(has_available_quantity=False)),
        available_quantity=Sum("available_qty", filter=(
            Q(source_run__status=SyncRun.Status.SUCCESS)
            & Q(source_run__failed_count=0)
            & Q(snapshot_at_utc__gte=now - FRESHNESS)
            & Q(internal_sku_id__isnull=False)
            & Q(site_code=F("warehouse__country_code"))
            & Q(has_available_quantity=True)
        )),
    )

    totals = {key: 0 for key in ("snapshots", "unknown", "failed", "stale", "unmapped", "country_conflicts")}
    known_by_country = {pk: 0 for pk in rows}
    for item in grouped:
        site_code = item["site_code"].upper()
        warehouse_code = (item["warehouse__country_code"] or "").upper()
        # A mismatched snapshot is visible only inside a country already
        # present in the caller's supply scope; attribute the reconciliation
        # count to its in-scope side and never merge its quantity.
        country = country_by_code.get(site_code) or country_by_code.get(warehouse_code)
        if country is None:
            continue
        row = rows[country.pk]
        for key in ("snapshots", "failed", "stale", "unmapped", "country_conflicts"):
            row[key] += int(item[key] or 0)
        row["unknown"] += int(item["missing"] or 0)
        known_by_country[country.pk] += int(item["available_quantity"] or 0)
        # A conflicting identity invalidates either selected country's total.
        other = country_by_code.get(warehouse_code)
        if item["country_conflicts"] and other and other.pk != country.pk:
            rows[other.pk]["country_conflicts"] += int(item["country_conflicts"])

    for row in rows.values():
        problems = any(row[key] for key in ("unknown", "failed", "stale", "unmapped", "country_conflicts"))
        row["status"] = "available" if row["snapshots"] and not problems else "partial" if row["snapshots"] or problems else "unavailable"
        row["available_quantity"] = known_by_country[row["country_id"]] if row["status"] == "available" else None
    any_partial = any(row["status"] == "partial" for row in rows.values())

    for row in rows.values():
        for key in totals:
            totals[key] += row[key]
    if all(row["status"] == "available" for row in rows.values()) and rows:
        totals["available_quantity"] = sum(row["available_quantity"] for row in rows.values())
        status = "available"
    else:
        totals["available_quantity"] = None
        status = "partial" if any_partial else "unavailable"
    return {"totals": totals, "countries": list(rows.values()), "status": status,
        "notice": base["notice"]}
