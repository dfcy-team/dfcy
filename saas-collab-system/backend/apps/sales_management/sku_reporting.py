"""Database projections for SKU reports over already authorized fact querysets."""
from decimal import Decimal

from django.db import connection
from django.db.models import Case, Count, F, Q, Sum, Value, When, Window
from django.db.models.functions import Collate, RowNumber
from rest_framework.exceptions import ValidationError

from apps.commerce.models import RefundReturnItem, SalesOrderItem
from apps.products.sku_aliases import filter_sku_codes


MONEY_FIELDS = ("gross_sales", "total_sales", "refund_amount", "cancelled_amount")
COUNT_FIELDS = ("units_sold", "total_units", "refund_units", "cancelled_units",
                "order_count", "valid_order_count", "cancelled_order_count")
DIMENSIONS = ("_report_sku", "_report_store", "_report_source", "_report_product",
              "_report_variant", "_report_currency")
LABELS = {"_stores": "store_name", "_platforms": "platform", "_seller_skus": "seller_sku",
          "_names": "product_name", "_products": "platform_product_id",
          "_variants": "platform_variant_id", "_variations": "variation"}


def _bucket():
    return {**dict.fromkeys(MONEY_FIELDS, Decimal(0)), **dict.fromkeys(COUNT_FIELDS, 0)}


def _exact(expression):
    # Python's original identities distinguish case, accents and trailing spaces.
    # MySQL's default collation (including utf8mb4_bin PAD SPACE) does not.
    collation = {"mysql": "utf8mb4_0900_bin", "postgresql": "C"}.get(connection.vendor, "BINARY")
    return Collate(expression, collation)


def _dimensions(items, parent, grouping):
    items = items.annotate(_source_seller=_exact(F("seller_sku")))
    mapped = Q(internal_sku_id__isnull=False)
    product = Case(When(_source_seller="", then=F("platform_product_id")), default=Value(""))
    variant = Case(When(_source_seller="", then=F("platform_variant_id")), default=Value(""))
    store, source = F(parent + "__store_id"), F("seller_sku")
    sku = Value(0)
    if grouping == "product":
        sku = F("internal_sku_id")
        store = Case(When(mapped, then=Value(None)), default=store)
        source = Case(When(mapped, then=Value("")), default=source)
        product = Case(When(mapped, then=Value("")), default=product)
        variant = Case(When(mapped, then=Value("")), default=variant)
    return items.annotate(_report_sku=sku, _report_store=store,
                          _report_source=_exact(source), _report_product=_exact(product),
                          _report_variant=_exact(variant), _report_currency=_exact(F("currency")),
                          _report_status=_exact(F(parent + "__normalized_status")),
                          _report_timezone=_exact(F(parent + "__store__timezone")))


def _partial_match(items, term):
    if not term:
        return items
    # Match the small distinct code catalogue with the original Unicode casefold
    # rule, rather than changing search semantics to a database collation.
    codes = items.annotate(_match_code=_exact(F("internal_sku__sku_code")))
    sellers, skus = set(), set()
    folded = term.casefold()
    for row in codes.values("_source_seller", "internal_sku_id", "_match_code").distinct():
        if folded in row["_source_seller"].casefold():
            sellers.add(row["_source_seller"])
        if row["internal_sku_id"] and folded in row["_match_code"].casefold():
            skus.add(row["internal_sku_id"])
    return items.filter(Q(_source_seller__in=sellers) | Q(internal_sku_id__in=skus))


def _measures(parent, is_refund):
    if is_refund:
        completed = Q(_report_status="completed")
        return {"refund_amount": Sum("refund_amount", filter=completed),
                "refund_units": Sum("quantity", filter=completed)}
    cancelled = Q(_report_status="cancelled")
    return {"gross_sales": Sum("line_total_amount", filter=~cancelled),
            "units_sold": Sum("quantity", filter=~cancelled),
            "total_sales": Sum("line_total_amount"), "total_units": Sum("quantity"),
            "cancelled_amount": Sum("line_total_amount", filter=cancelled),
            "cancelled_units": Sum("quantity", filter=cancelled),
            "order_count": Count(parent, distinct=True),
            "valid_order_count": Count(parent, distinct=True, filter=~cancelled),
            "cancelled_order_count": Count(parent, distinct=True, filter=cancelled)}


def _add(target, source):
    for field in MONEY_FIELDS + COUNT_FIELDS:
        value = source.get(field)
        if value is not None:
            if field in MONEY_FIELDS:
                value = Decimal(value).quantize(Decimal("0.0001"))
            target[field] += value


def aggregate_sku_facts(orders, refunds, grouping, term, sku_mode, mapping_as_of):
    from .reporting import _local_daily_groups

    rows, days, summaries = {}, {}, {}
    sources, target_ids = [], set()
    for model, parents, parent in ((SalesOrderItem, orders, "sales_order"),
                                   (RefundReturnItem, refunds, "refund_return")):
        items = model.objects.filter(**{parent + "__in": parents}).order_by()
        if sku_mode:
            items = filter_sku_codes(items, tenant_id=parents.values_list("tenant_id", flat=True).first(),
                                     code=term, mode=sku_mode, store_field=parent + "__store_id",
                                     mapping_as_of=mapping_as_of)
            if term and sku_mode == "related":
                target_ids.update(items.exclude(internal_sku=None).values_list("internal_sku_id", flat=True)
                                  .distinct().order_by()[:2])
        items = _dimensions(items, parent, grouping)
        if not sku_mode:
            items = _partial_match(items, term)
        sources.append((model, parent, items))
    if len(target_ids) > 1:
        raise ValidationError({"sku": "销售与退款中的该编码对应多个商品，请限定店铺或映射日期后核对。"})

    for model, parent, items in sources:
        # One header per identity retains the original first-item SKU label and
        # stable tie order, even when source codes have inconsistent mappings.
        partition = DIMENSIONS if grouping == "product" else DIMENSIONS[1:]
        heads = items.annotate(_header_mapped=Case(When(internal_sku_id__isnull=False, then=Value(True)), default=Value(False)),
                              _first=Window(RowNumber(), partition_by=[F(field) for field in partition],
                                            order_by=[F(parent + "_id").asc(), F("pk").asc()]))
        for head in heads.filter(_first=1).order_by(parent + "_id", "pk").values(
                *DIMENSIONS, "_header_mapped", "internal_sku__sku_code", "seller_sku"):
            key = tuple(head[field] for field in DIMENSIONS)
            rows.setdefault(key, {**_bucket(), "sku": head["internal_sku__sku_code"] if head["_header_mapped"] else head["seller_sku"],
                                  "internal_sku": head["internal_sku__sku_code"] if head["_header_mapped"] else None,
                                  "currency": head["_report_currency"],
                                  "mapping_status": "mapped" if head["_header_mapped"] else "unmapped",
                                  **{field: set() for field in LABELS}})
        measures = _measures(parent, model == RefundReturnItem)
        for facts in items.values(*DIMENSIONS).annotate(**measures):
            _add(rows[tuple(facts[field] for field in DIMENSIONS)], facts)

        labels = {"store_name": _exact(F(parent + "__store__name")),
                  "platform": _exact(F(parent + "__platform__platform_type")),
                  "seller_sku_label": _exact(F("seller_sku")),
                  "product_name": _exact(F("item_name_snapshot")),
                  "platform_product_id_label": _exact(F("platform_product_id")),
                  "platform_variant_id_label": _exact(F("platform_variant_id")),
                  "variation": _exact(F("variation_snapshot") if model == SalesOrderItem else Value(""))}
        label_fields = dict(LABELS, _seller_skus="seller_sku_label", _products="platform_product_id_label",
                            _variants="platform_variant_id_label")
        for label in items.annotate(**labels).values(*DIMENSIONS, *labels).distinct():
            target = rows[tuple(label[field] for field in DIMENSIONS)]
            for field, source in label_fields.items():
                if label[source] or field in ("_stores", "_platforms"):
                    target[field].add(label[source])

        timestamp = "created_at_utc" if model == SalesOrderItem else "requested_at_utc"
        for facts in _local_daily_groups(items, parent + "__" + timestamp, "_report_timezone",
                                        ["_report_currency"], measures):
            date, currency = facts["local_day"].isoformat(), facts["_report_currency"]
            _add(days.setdefault((date, currency), {**_bucket(), "date": date, "currency": currency}), facts)
            # An order belongs to one store/local day; summing daily distinct
            # counts remains distinct per currency across the complete range.
            _add(summaries.setdefault(currency, _bucket()), facts)
    return rows, days, summaries
