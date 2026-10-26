"""Bounded product dimension aggregates for the realtime sales board."""

from django.db.models import Case, CharField, Count, F, Max, Min, Q, Sum, Value, When, Window
from django.db.models.functions import Cast, Coalesce, Concat, Length, RowNumber

from apps.commerce.models import SalesOrderItem
from apps.sales_management.views import ZERO, _decimal_string


DIMENSIONS = ("store_spu", "store_sku", "product_spu", "product_sku", "category")


def _base_queryset(valid_orders):
    return SalesOrderItem.objects.filter(sales_order__in=valid_orders)


def _ranked(queryset, keys):
    fields = ["sales_order__currency", *keys]
    return queryset.order_by().values(*fields).annotate(
        sales_amount=Sum("line_total_amount"),
        units_sold=Sum("quantity"),
        name=Max("item_name_snapshot"),
        line_count=Count("pk"),
        mapped_count=Count("pk", filter=Q(internal_sku_id__isnull=False)),
        mapped_sku_id=Max("internal_sku_id"),
        site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"),
        inventory_type=Max("internal_sku__inventory_type"),
    ).annotate(
        amount_rank=Window(
            expression=RowNumber(), partition_by=[F("sales_order__currency")],
            order_by=[F("sales_amount").desc(), *[F(key).asc() for key in keys]],
        ),
        units_rank=Window(
            expression=RowNumber(), partition_by=[F("sales_order__currency")],
            order_by=[F("units_sold").desc(), *[F(key).asc() for key in keys]],
        ),
    ).filter(Q(amount_rank__lte=10) | Q(units_rank__lte=10)).order_by(
        "sales_order__currency", "amount_rank"
    )


def _append(groups, dimension, rows, key_fields, *, system_sku=False):
    for row in rows:
        currency = row["sales_order__currency"]
        group = groups.setdefault(currency, {"currency": currency})
        rankings = group.setdefault("product_rankings", {}).setdefault(
            dimension, {"sales_amount": [], "units_sold": []}
        )
        values = [row[field] for field in key_fields]
        key = row.get("public_key") or ":".join(str(value or "") for value in values)
        code = row.get("public_code") or ""
        name = row.get("public_name") or row.get("name") or code or key
        if dimension == "category":
            name = name.strip("/")
        if row.get("_spu_key") == "unmapped" or row.get("_sku_key") == "unmapped":
            name, code = "未映射", "unmapped"
        if row.get("_category_key") == "unmapped":
            name, code = "未映射", "unmapped"
        elif row.get("_category_key") == "unclassified":
            name, code = "未分类", "unclassified"
        item = {
            "key": key, "name": name, "code": code,
            "sales_amount": _decimal_string(row["sales_amount"] or ZERO),
            "units_sold": int(row["units_sold"] or 0),
        }
        if system_sku:
            mapped_count = int(row["mapped_count"] or 0)
            line_count = int(row["line_count"] or 0)
            gap_count = max(line_count - mapped_count, 0)
            item.update({
                "mapping_status": "unmapped" if mapped_count == 0 else "partial" if gap_count else "mapped",
                "mapping_gap_count": gap_count,
                "mapping_reason": "部分销售行未映射" if gap_count and mapped_count else "存在未映射销售行" if gap_count else "",
            })
        if system_sku and row["mapped_count"] > 0 and row["sku_identity_count"] == 1 and row["mapped_sku_id"]:
            item.update({
                "internal_sku_id": row["mapped_sku_id"],
                "inventory_site": row["site_min"] if row["site_min"] == row["site_max"] else None,
                "inventory_type": row["inventory_type"],
            })
            if dimension == "product_sku":
                item["drill_internal_sku_id"] = row["mapped_sku_id"]
        if row["amount_rank"] <= 10:
            rankings["sales_amount"].append(item)
        if row["units_rank"] <= 10:
            rankings["units_sold"].append({**item, "_rank": row["units_rank"]})
    for group in groups.values():
        dimension_rows = group.get("product_rankings", {}).get(dimension)
        if not dimension_rows:
            continue
        units = dimension_rows["units_sold"]
        units.sort(key=lambda item: item.get("_rank", 0))
        for ranked_item in units:
            ranked_item.pop("_rank", None)


def attach_product_rankings(valid_orders, groups, tenant_id):
    """Attach five currency-partitioned top-ten dimensions using SQL aggregation."""
    base = _base_queryset(valid_orders)

    # Store identities use platform IDs plus store ID; blank IDs get a line-unique key.
    product_identity = Case(
        When(platform_product_id="", then=Concat(Value("line:"), Cast("pk", CharField()))),
        default=Concat(Value("p:"), Cast(Length("platform_product_id"), CharField()), Value(":"), F("platform_product_id")),
        output_field=CharField(),
    )
    base_store = base.annotate(_product=product_identity).annotate(
        _variant=Case(
            When(platform_variant_id__gt="", then=Concat(Value("v:"), Cast(Length("platform_variant_id"), CharField()), Value(":"), F("platform_variant_id"))),
            When(seller_sku__gt="", then=Concat(Value("s:"), Cast(Length("seller_sku"), CharField()), Value(":"), F("seller_sku"))),
            default=Concat(Value("line:"), Cast("pk", CharField())), output_field=CharField(),
        )
    )
    store_spu = base_store.values(
        "sales_order__currency", "sales_order__store_id", "_product"
    ).annotate(
        public_key=Concat(Value("store:"), Cast("sales_order__store_id", CharField()), Value(":"), F("_product")),
        public_code=Max("platform_product_id"), public_name=Concat(Max("sales_order__store__name"), Value(" · "), Max("item_name_snapshot")),
        sales_amount=Sum("line_total_amount"), units_sold=Sum("quantity"), name=Max("item_name_snapshot"),
        line_count=Count("pk"), mapped_count=Count("pk", filter=Q(internal_sku_id__isnull=False)),
        mapped_sku_id=Max(Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku_id")), default=Value(None))), site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"), inventory_type=Max(Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__inventory_type")), default=Value(None))),
        sku_identity_count=Count("internal_sku_id", distinct=True), internal_sku_code=Max("internal_sku__sku_code"),
    ).annotate(
        amount_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("sales_amount").desc(), F("sales_order__store_id").asc(), F("_product").asc()]),
        units_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("units_sold").desc(), F("sales_order__store_id").asc(), F("_product").asc()]),
    ).filter(Q(amount_rank__lte=10) | Q(units_rank__lte=10)).order_by("sales_order__currency", "amount_rank")
    _append(groups, "store_spu", store_spu, ["sales_order__store_id", "_product"])

    store_sku = base_store.annotate(_identity=Concat(F("_product"), F("_variant"))).values(
        "sales_order__currency", "sales_order__store_id", "_identity"
    ).annotate(
        public_key=Concat(Value("store:"), Cast("sales_order__store_id", CharField()), Value(":"), F("_identity")),
        public_code=Max(Case(When(platform_variant_id="", then=F("seller_sku")), default=F("platform_variant_id"), output_field=CharField())),
        public_name=Concat(Max("sales_order__store__name"), Value(" · "), Max("item_name_snapshot")),
        sales_amount=Sum("line_total_amount"), units_sold=Sum("quantity"), name=Max("item_name_snapshot"),
        line_count=Count("pk"), mapped_count=Count("pk", filter=Q(internal_sku__tenant_id=tenant_id)),
        mapped_sku_id=Max("internal_sku_id", filter=Q(internal_sku__tenant_id=tenant_id)), site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"), inventory_type=Max("internal_sku__inventory_type", filter=Q(internal_sku__tenant_id=tenant_id)),
        sku_identity_count=Count("internal_sku_id", distinct=True, filter=Q(internal_sku__tenant_id=tenant_id)),
        internal_sku_code=Max(Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__sku_code")), default=Value(None))),
    ).annotate(
        amount_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("sales_amount").desc(), F("sales_order__store_id").asc(), F("_identity").asc()]),
        units_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("units_sold").desc(), F("sales_order__store_id").asc(), F("_identity").asc()]),
    ).filter(Q(amount_rank__lte=10) | Q(units_rank__lte=10)).order_by("sales_order__currency", "amount_rank")
    _append(groups, "store_sku", store_sku, ["sales_order__store_id", "_identity"], system_sku=True)

    # Only same-tenant canonical links participate in system dimensions.
    spu_id = Case(
        When(internal_spu__tenant_id=tenant_id, then=F("internal_spu_id")),
        When(internal_spu__isnull=True, internal_sku__tenant_id=tenant_id, then=F("internal_sku__spu_id")),
        default=Value(None),
    )
    base_system = base.annotate(_spu=spu_id).annotate(
        _spu_code=Case(When(internal_spu__tenant_id=tenant_id, then=F("internal_spu__spu_code")),
                       When(internal_spu__isnull=True, internal_sku__tenant_id=tenant_id, then=F("internal_sku__spu__spu_code")),
                       default=Value(""), output_field=CharField()),
        _spu_name=Case(When(internal_spu__tenant_id=tenant_id, then=F("internal_spu__product_name")),
                       When(internal_spu__isnull=True, internal_sku__tenant_id=tenant_id, then=F("internal_sku__spu__product_name")),
                       default=Value(""), output_field=CharField()),
    )
    product_spu = base_system.filter(_spu__isnull=False).annotate(_spu_key=Cast("_spu", CharField())).values(
        "sales_order__currency", "_spu_key", public_key=Concat(Value("spu:"), F("_spu_key")),
        public_code=F("_spu_code"), public_name=F("_spu_name"),
    )
    product_spu = _ranked_from_group(product_spu, ["_spu_key"])
    _append(groups, "product_spu", product_spu, ["_spu_key"])

    valid_sku = base.annotate(_sku_id=Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku_id")), default=Value(None))).annotate(
        _sku_key=Coalesce(Cast("_sku_id", CharField()), Value("unmapped")),
        _sku_code=Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__sku_code")), default=Value(""), output_field=CharField()),
        _sku_name=Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__product_name")), default=Value(""), output_field=CharField()),
    )
    product_sku = valid_sku.filter(_sku_id__isnull=False).values("sales_order__currency", "_sku_key", public_key=Concat(Value("sku:"), F("_sku_key")), public_code=F("_sku_code"), public_name=F("_sku_name"))
    product_sku = _ranked_from_group(product_sku, ["_sku_key"], tenant_id=tenant_id, mapped_id="_sku_id")
    _append(groups, "product_sku", product_sku, ["_sku_key"], system_sku=True)

    category_node = Case(
        When(_spu__isnull=False, internal_spu__isnull=False, internal_spu__tenant_id=tenant_id,
             internal_spu__category_node__tenant_id=tenant_id, then=F("internal_spu__category_node_id")),
        When(_spu__isnull=False, internal_spu__isnull=True, internal_sku__tenant_id=tenant_id,
             internal_sku__spu__category_node__tenant_id=tenant_id, then=F("internal_sku__spu__category_node_id")),
        default=Value(None),
    )
    cat_base = base_system.filter(_spu__isnull=False).annotate(_category=category_node).annotate(
        _category_key=Case(
                           When(_category__isnull=True, then=Value("unclassified")),
                           default=Concat(Value("category:"), Cast("_category", CharField())), output_field=CharField()),
    )
    # For SKU-derived SPUs, use that SPU's category fields through the canonical FK.
    cat_base = cat_base.annotate(
        _cat_code=Case(When(_category__isnull=False, internal_spu__isnull=False, then=F("internal_spu__category_node__code")), When(_category__isnull=False, then=F("internal_sku__spu__category_node__code")), default=Value(""), output_field=CharField()),
        _cat_name=Case(When(_category__isnull=False, internal_spu__isnull=False, then=F("internal_spu__category_node__name")), When(_category__isnull=False, then=F("internal_sku__spu__category_node__name")), default=Value(""), output_field=CharField()),
        _cat_parent=Case(When(_category__isnull=False, internal_spu__isnull=False, then=F("internal_spu__category_node__parent__name")), When(_category__isnull=False, then=F("internal_sku__spu__category_node__parent__name")), default=Value(""), output_field=CharField()),
        _cat_root=Case(When(_category__isnull=False, internal_spu__isnull=False, then=F("internal_spu__category_node__parent__parent__name")), When(_category__isnull=False, then=F("internal_sku__spu__category_node__parent__parent__name")), default=Value(""), output_field=CharField()),
    ).annotate(_cat_path=Concat(Coalesce(F("_cat_root"), Value("")), Value("/"), Coalesce(F("_cat_parent"), Value("")), Value("/"), Coalesce(F("_cat_name"), Value(""))))
    category = cat_base.values("sales_order__currency", "_category_key", public_key=F("_category_key"), public_code=F("_cat_code"), public_name=F("_cat_path"))
    category = _ranked_from_group(category, ["_category_key"])
    _append(groups, "category", category, ["_category_key"])
    for group in groups.values():
        rankings = group.setdefault("product_rankings", {})
        group.setdefault("product_mapping_note", "未映射销售行不计入系统商品 SPU、SKU 和分类排行。")
        for dimension in DIMENSIONS:
            rankings.setdefault(dimension, {"sales_amount": [], "units_sold": []})


def _ranked_from_group(queryset, keys, tenant_id=None, mapped_id="internal_sku_id"):
    """Add metric sums and top-ten windows after a dimension's identity annotations."""
    # Existing grouping keys are retained by values() as Django grouping columns.
    return queryset.annotate(
        sales_amount=Sum("line_total_amount"), units_sold=Sum("quantity"), name=Max("item_name_snapshot"),
        line_count=Count("pk"), mapped_count=Count("pk", filter=Q(internal_sku__tenant_id=tenant_id) if tenant_id is not None else Q(internal_sku_id__isnull=False)),
        mapped_sku_id=Max(mapped_id), site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"), inventory_type=Max("internal_sku__inventory_type"),
        sku_identity_count=Count(mapped_id, distinct=True, filter=Q(internal_sku__tenant_id=tenant_id) if tenant_id is not None else Q(internal_sku_id__isnull=False)),
        internal_sku_code=Max("internal_sku__sku_code"),
    ).annotate(
        amount_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("sales_amount").desc(), *[F(key).asc() for key in keys]]),
        units_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("units_sold").desc(), *[F(key).asc() for key in keys]]),
    ).filter(Q(amount_rank__lte=10) | Q(units_rank__lte=10)).order_by("sales_order__currency", "amount_rank")
