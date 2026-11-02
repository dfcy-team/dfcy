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
        tenant_id=Max("sales_order__tenant_id"), platform_id=Max("sales_order__platform_id"), store_id=Max("sales_order__store_id"),
        variant_id=Max("platform_variant_id"), variant_count=Count("platform_variant_id", distinct=True), store_count=Count("sales_order__store_id", distinct=True),
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
        item.update({
            "_image_key": (row.get("tenant_id"), row.get("platform_id"), row.get("store_id"), row.get("variant_id"))
            if row.get("store_count") == 1 and row.get("variant_count") == 1 and row.get("variant_id") else None,
            "_spu_image_key": None,
            "platform_image_url": "",
        })
        if dimension == "product_spu" and row.get("mapped_spu_id"):
            item.update(mapped_spu_id=row["mapped_spu_id"], inventory_countries=[row["site_min"]] if row.get("site_min") and row.get("site_min") == row.get("site_max") else [])
        elif dimension == "store_spu" and row.get("mapped_spu_id") and row.get("mapped_spu_count") == 1:
            item.update(mapped_spu_id=row["mapped_spu_id"], inventory_countries=[row["site_min"]] if row.get("site_min") and row.get("site_min") == row.get("site_max") else [])
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
        if any(str(row.get(field, "")).startswith("unmapped:") for field in ("_spu_key", "_sku_key")):
            item.update(mapping_status="unmapped", mapping_reason="待映射", store_id=row["source_store_id"], store_name=row["source_store_name"], platform_name=row["source_platform_name"], platform_product_id=row["source_product_id"], platform_variant_id=row["source_variant_id"], platform_sku=row["source_seller_sku"])
            item["code"] = row["source_product_id"] if dimension == "product_spu" else (row["source_variant_id"] or row["source_seller_sku"] or row["source_product_id"])
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
    variant_identity = Case(
        When(platform_variant_id__gt="", then=Concat(Value("v:"), Cast(Length("platform_variant_id"), CharField()), Value(":"), F("platform_variant_id"))),
        When(seller_sku__gt="", then=Concat(Value("s:"), Cast(Length("seller_sku"), CharField()), Value(":"), F("seller_sku"))),
        default=Concat(Value("line:"), Cast("pk", CharField())), output_field=CharField(),
    )
    base_store = base.annotate(_product=product_identity, _variant=variant_identity)
    store_spu = base_store.values(
        "sales_order__currency", "sales_order__store_id", "_product"
    ).annotate(
        public_key=Concat(Value("store:"), Cast("sales_order__store_id", CharField()), Value(":"), F("_product")),
        public_code=Max("platform_product_id"), public_name=Concat(Max("sales_order__store__name"), Value(" · "), Max("item_name_snapshot")),
        sales_amount=Sum("line_total_amount"), units_sold=Sum("quantity"), name=Max("item_name_snapshot"),
        tenant_id=Max("sales_order__tenant_id"), platform_id=Max("sales_order__platform_id"), store_id=Max("sales_order__store_id"),
        variant_id=Max("platform_variant_id"), variant_count=Count("platform_variant_id", distinct=True), store_count=Count("sales_order__store_id", distinct=True),
        line_count=Count("pk"), mapped_count=Count("pk", filter=Q(internal_sku_id__isnull=False)),
        mapped_sku_id=Max(Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku_id")), default=Value(None))), site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"), inventory_type=Max(Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__inventory_type")), default=Value(None))),
        sku_identity_count=Count("internal_sku_id", distinct=True), internal_sku_code=Max("internal_sku__sku_code"),
        mapped_spu_id=Max(Case(When(internal_spu__tenant_id=tenant_id, then=F("internal_spu_id")), When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__spu_id")), default=Value(None))),
        mapped_spu_count=Count(Case(When(internal_spu__tenant_id=tenant_id, then=F("internal_spu_id")), When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__spu_id")), default=Value(None)), distinct=True),
    ).annotate(
        amount_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("sales_amount").desc(), F("sales_order__store_id").asc(), F("_product").asc()]),
        units_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("units_sold").desc(), F("sales_order__store_id").asc(), F("_product").asc()]),
    ).filter(Q(amount_rank__lte=10) | Q(units_rank__lte=10)).order_by("sales_order__currency", "amount_rank")
    _append(groups, "store_spu", store_spu, ["sales_order__store_id", "_product"])

    store_sku = base_store.annotate(_identity=Concat(F("_product"), F("_variant"))).values(
        "sales_order__currency", "sales_order__store_id", "_identity"
    ).annotate(
        tenant_id=Max("sales_order__tenant_id"), platform_id=Max("sales_order__platform_id"), store_id=Max("sales_order__store_id"),
        variant_id=Max("platform_variant_id"), variant_count=Count("platform_variant_id", distinct=True), store_count=Count("sales_order__store_id", distinct=True),
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
    fallback_spu = Concat(Value("unmapped:"), Cast("sales_order__store_id", CharField()), Value(":"), product_identity)
    fallback_sku = Concat(fallback_spu, Value(":"), variant_identity)
    product_spu = base_system.annotate(_spu_key=Coalesce(Cast("_spu", CharField()), fallback_spu)).values(
        "sales_order__currency", "_spu_key", public_key=Concat(Value("spu:"), F("_spu_key")),
        public_code=F("_spu_code"), public_name=F("_spu_name"),
        mapped_spu_id=F("_spu"),
    )
    product_spu = _ranked_from_group(product_spu, ["_spu_key"])
    _append(groups, "product_spu", product_spu, ["_spu_key"])

    valid_sku = base.annotate(_sku_id=Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku_id")), default=Value(None))).annotate(
        _sku_key=Coalesce(Cast("_sku_id", CharField()), fallback_sku),
        _sku_code=Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__sku_code")), default=Value(""), output_field=CharField()),
        _sku_name=Case(When(internal_sku__tenant_id=tenant_id, then=F("internal_sku__product_name")), default=Value(""), output_field=CharField()),
    )
    product_sku = valid_sku.values("sales_order__currency", "_sku_key", public_key=Concat(Value("sku:"), F("_sku_key")), public_code=F("_sku_code"), public_name=F("_sku_name"))
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
        group.setdefault("product_mapping_note", "未映射商品按店铺及平台商品身份单列，待补全映射；分类排行仅统计已映射商品。")
        for dimension in DIMENSIONS:
            rankings.setdefault(dimension, {"sales_amount": [], "units_sold": []})
    from apps.listings.models import PlatformProductDetail
    # Only fetch full country sets for an SPU whose sales span multiple sites;
    # the common single-country case uses the aggregated min/max in the row.
    multi_site_spus = {item["mapped_spu_id"] for group in groups.values() for metric in ("sales_amount", "units_sold") for item in group.get("product_rankings", {}).get("product_spu", {}).get(metric, []) if item.get("mapped_spu_id") and not item.get("inventory_countries")}
    if multi_site_spus:
        country_by_currency_spu = {}
        for currency, spu_value, country in base_system.filter(_spu__in=multi_site_spus).values_list("sales_order__currency", "_spu", "sales_order__store__country_code").distinct():
            country_by_currency_spu.setdefault((currency, spu_value), set()).add(country)
        for group in groups.values():
            for metric in ("sales_amount", "units_sold"):
                for item in group.get("product_rankings", {}).get("product_spu", {}).get(metric, []):
                    country_key = (group["currency"], item.get("mapped_spu_id"))
                    if country_key in country_by_currency_spu:
                        item["inventory_countries"] = sorted(country_by_currency_spu[country_key])
    image_keys = {item["_image_key"] for group in groups.values() for dimension in DIMENSIONS for metric in ("sales_amount", "units_sold") for item in group.get("product_rankings", {}).get(dimension, {}).get(metric, []) if item.get("_image_key")}
    spu_ids = {item["mapped_spu_id"] for group in groups.values() for metric in ("sales_amount", "units_sold") for item in group.get("product_rankings", {}).get("product_spu", {}).get(metric, []) if item.get("mapped_spu_id")}
    representative = {}
    if spu_ids:
        contributing = base_system.filter(_spu__in=spu_ids, platform_product_id__gt="").order_by(
            "sales_order__currency", "_spu", "sales_order__platform_id", "sales_order__store_id", "platform_product_id"
        ).values_list("sales_order__currency", "_spu", "sales_order__platform_id", "sales_order__store_id", "platform_product_id").distinct()
        for currency, spu_id, platform_id, store_id, product_id in contributing.iterator(chunk_size=1000):
            representative.setdefault((currency, spu_id), (tenant_id, platform_id, store_id, product_id))
    for group in groups.values():
        for metric in ("sales_amount", "units_sold"):
            for item in group.get("product_rankings", {}).get("product_spu", {}).get(metric, []):
                item["_spu_image_key"] = representative.get((group["currency"], item.get("mapped_spu_id")))
    spu_image_keys = {item["_spu_image_key"] for group in groups.values() for metric in ("sales_amount", "units_sold") for item in group.get("product_rankings", {}).get("product_spu", {}).get(metric, []) if item.get("_spu_image_key")}
    image_by_key = {}
    spu_image_by_key = {}
    detail_filter = Q(pk__in=[])
    for key in image_keys:
        detail_filter |= Q(platform_id=key[1], store_id=key[2], platform_variant_id=key[3])
    for key in spu_image_keys:
        detail_filter |= Q(platform_id=key[1], store_id=key[2], platform_product_id=key[3])
    if image_keys or spu_image_keys:
        details = PlatformProductDetail.objects.filter(tenant_id=tenant_id).filter(detail_filter).exclude(platform_image_url="").order_by("tenant_id", "platform_id", "store_id", "platform_product_id", "platform_variant_id", "pk").only("tenant_id", "platform_id", "store_id", "platform_product_id", "platform_variant_id", "platform_image_url")
        for detail in details:
            image_by_key[(detail.tenant_id, detail.platform_id, detail.store_id, detail.platform_variant_id)] = detail.platform_image_url
            spu_image_by_key.setdefault((detail.tenant_id, detail.platform_id, detail.store_id, detail.platform_product_id), detail.platform_image_url)
    for group in groups.values():
        for dimension in DIMENSIONS:
            for metric in ("sales_amount", "units_sold"):
                for item in group.get("product_rankings", {}).get(dimension, {}).get(metric, []):
                    key = item.pop("_image_key", None)
                    item["platform_image_url"] = image_by_key.get(key, "") if key else ""
                    spu_key = item.pop("_spu_image_key", None)
                    if spu_key:
                        item["platform_image_url"] = spu_image_by_key.get(spu_key, "")


def _ranked_from_group(queryset, keys, tenant_id=None, mapped_id="internal_sku_id"):
    """Add metric sums and top-ten windows after a dimension's identity annotations."""
    # Existing grouping keys are retained by values() as Django grouping columns.
    return queryset.annotate(
        source_store_id=Min("sales_order__store_id"), source_store_name=Max("sales_order__store__name"), source_platform_name=Max("sales_order__platform__name"),
        source_product_id=Max("platform_product_id"), source_variant_id=Max("platform_variant_id"), source_seller_sku=Max("seller_sku"),
        sales_amount=Sum("line_total_amount"), units_sold=Sum("quantity"), name=Max("item_name_snapshot"),
        tenant_id=Max("sales_order__tenant_id"), platform_id=Max("sales_order__platform_id"), store_id=Max("sales_order__store_id"),
        variant_id=Max("platform_variant_id"), variant_count=Count("platform_variant_id", distinct=True), store_count=Count("sales_order__store_id", distinct=True),
        line_count=Count("pk"), mapped_count=Count("pk", filter=Q(internal_sku__tenant_id=tenant_id) if tenant_id is not None else Q(internal_sku_id__isnull=False)),
        mapped_sku_id=Max(mapped_id), site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"), inventory_type=Max("internal_sku__inventory_type"),
        sku_identity_count=Count(mapped_id, distinct=True, filter=Q(internal_sku__tenant_id=tenant_id) if tenant_id is not None else Q(internal_sku_id__isnull=False)),
        internal_sku_code=Max("internal_sku__sku_code"),
    ).annotate(
        amount_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("sales_amount").desc(), *[F(key).asc() for key in keys]]),
        units_rank=Window(expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("units_sold").desc(), *[F(key).asc() for key in keys]]),
    ).filter(Q(amount_rank__lte=10) | Q(units_rank__lte=10)).order_by("sales_order__currency", "amount_rank")
