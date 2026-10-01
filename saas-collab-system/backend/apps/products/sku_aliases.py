"""Permission-scoped exact alias resolution over indexed identity records."""
import hashlib
from datetime import UTC, date, datetime, time

from django.db.models import CharField, Func, Q, Subquery, Value
from rest_framework.exceptions import ValidationError

from .models import ProductLegacyItem, ProductSKU, ProductSKUAlias


def code_key(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def validate_sku_mode(mode, mapping_as_of=""):
    if mode not in ("", "related", "source"):
        raise ValidationError({"sku_mode": "请选择同商品关联查询或原始来源编码核对。"})
    if mapping_as_of:
        try:
            date.fromisoformat(str(mapping_as_of))
        except (ValueError, TypeError) as exc:
            raise ValidationError({"mapping_as_of": "映射日期应为 YYYY-MM-DD。"}) from exc


def alias_at(queryset, mapping_as_of):
    if not mapping_as_of:
        return queryset
    at = datetime.combine(date.fromisoformat(str(mapping_as_of)), time.min, tzinfo=UTC)
    return queryset.filter(effective_from__lte=at).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=at))


def filter_sku_codes(queryset, *, tenant_id, code, mode="", source_field="seller_sku",
                     internal_field="internal_sku_id", store_field=None, warehouse_field=None,
                     mapping_as_of="", partial=False):
    """Resolve only targets present in the already authorized fact queryset.

    No aliases are exposed to report callers. A recycled/ambiguous code requires
    a store/warehouse/date filter instead of selecting an arbitrary target.
    Unmapped exact-source facts remain visible as separate, unmapped records.
    """
    validate_sku_mode(mode, mapping_as_of)
    if not code:
        return queryset
    if len(code) > 160 or "\x00" in code:
        raise ValidationError({"sku": "SKU 编码不能超过 160 个字符或包含空字符。"})
    current_field = internal_field.removesuffix("_id") + "__sku_code"
    exact_code = code
    if mode:
        from django.db import connection
        from django.db.models.functions import Collate
        if connection.vendor == "mysql":
            # utf8mb4_bin uses PAD SPACE; the indexed source predicate below
            # narrows candidates, and SHA2 keeps trailing spaces distinct.
            expression = Func(source_field, Value(256), function="SHA2", output_field=CharField(max_length=64))
            exact_code = code_key(code)
        else:
            expression = Collate(source_field, "C" if connection.vendor == "postgresql" else "BINARY")
        queryset = queryset.annotate(_sku_source_code=expression)
    if mode == "source":
        return queryset.filter(**{source_field: code}, _sku_source_code=exact_code)
    if not mode:
        lookup = "__icontains" if partial else ""
        return queryset.filter(Q(**{source_field + lookup: code}) | Q(**{current_field + lookup: code}))

    aliases = ProductSKUAlias.objects.filter(tenant_id=tenant_id, code_key=code_key(code))
    scopes = ["tenant"] + (["store"] if store_field else []) + (["warehouse"] if warehouse_field else [])
    records = list(aliases.filter(scope_type__in=scopes).values("sku_id", "scope_type", "store_id", "warehouse_id", "effective_from", "effective_to")[:201])
    if len(records) > 200:
        raise ValidationError({"sku": "该编码历史映射过多，请先在商品主数据核对。"})
    known, active = Q(pk__in=[]), Q(pk__in=[])
    at = datetime.combine(date.fromisoformat(str(mapping_as_of)), time.min, tzinfo=UTC) if mapping_as_of else None
    for record in records:
        condition = Q(**{internal_field: record["sku_id"]})
        if record["scope_type"] == "store":
            condition &= Q(**{store_field: record["store_id"]})
        elif record["scope_type"] == "warehouse":
            condition &= Q(**{warehouse_field: record["warehouse_id"]})
        known |= condition
        if at is None or (record["effective_from"] <= at and (not record["effective_to"] or at < record["effective_to"])):
            active |= condition

    # Python equality protects case/leading zeros from MySQL collation folding.
    catalogue = list(ProductSKU.objects.filter(tenant_id=tenant_id).filter(Q(sku_code=code) | Q(legacy_sku_code=code)).values_list("id", "sku_code", "legacy_sku_code")[:51])
    if len(catalogue) > 50:
        raise ValidationError({"sku": "历史编码存在过多映射，需先核对。"})
    direct, legacy = set(), set()
    for sku_id, current, old in catalogue:
        if current == code:
            direct.add(sku_id)
        if old == code:
            legacy.add(sku_id)
    legacy_rows = ProductLegacyItem.objects.filter(tenant_id=tenant_id, legacy_sku_code=code, status="generated", generated_sku__tenant_id=tenant_id).values_list("legacy_sku_code", "generated_sku_id")[:51]
    legacy.update(sku_id for old, sku_id in legacy_rows if old == code and sku_id)
    # Explicit dated records supersede the undated legacy field for that target.
    source_match = Q(**{source_field: code}, _sku_source_code=exact_code)
    match = Q(**{internal_field + "__in": direct}) | active
    match |= ~known & (Q(**{internal_field + "__in": legacy}) | source_match)
    targets = list(queryset.filter(match).exclude(**{internal_field + "__isnull": True}).values_list(internal_field, flat=True).distinct().order_by()[:2])
    if len(targets) > 1:
        raise ValidationError({"sku": "该编码对应多个商品，请限定店铺/仓库或映射日期后核对。"})
    selected = Q(**{source_field: code, internal_field + "__isnull": True}, _sku_source_code=exact_code)
    if targets:
        selected |= Q(**{internal_field: targets[0]})
    return queryset.filter(selected)


def latest_identity_inventory(queryset, *, daily=False, evidence_queryset=None):
    """Keep one stock observation per stable SKU; reject same-batch aliases.

    A source-code query remains available to inspect ambiguous source rows.
    """
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber, TruncDate
    base = queryset.order_by()
    partition = [F("site_code"), F("warehouse_id"), F("internal_sku_id")]
    if daily:
        base = base.annotate(_identity_day=TruncDate("snapshot_at_utc", tzinfo=UTC))
        partition.append(F("_identity_day"))
    mapped = base.filter(internal_sku__isnull=False)
    evidence = mapped
    if evidence_queryset is not None:
        identities = list(mapped.values("site_code", "warehouse_id", "internal_sku_id").distinct().order_by()[:1001])
        if len(identities) > 1000:
            raise ValidationError({"sku": "关联仓库范围过大，请先限定仓库。"})
        allowed = Q(pk__in=[])
        for identity in identities:
            allowed |= Q(**identity)
        evidence = evidence_queryset.filter(allowed)
    # Two codes in the same ingestion batch are not proven to be a rename.
    from django.db import connection
    from django.db.models import Count
    from django.db.models.functions import Collate
    source_identity = Func("source_sku", Value(256), function="SHA2", output_field=CharField(max_length=64)) if connection.vendor == "mysql" else Collate("source_sku", "C" if connection.vendor == "postgresql" else "BINARY")
    if evidence.values("site_code", "warehouse_id", "internal_sku_id", "source_run_id").annotate(n=Count(source_identity, distinct=True)).filter(n__gt=1).exists():
        raise ValidationError({"sku": "同批次存在多个来源编码的库存，需按原始来源编码核对，不能自动累计。"})
    ids = mapped.annotate(_identity_rank=Window(expression=RowNumber(), partition_by=partition,
                         order_by=[F("snapshot_at_utc").desc(), F("pk").desc()])).filter(_identity_rank=1).values("pk")
    return base.filter(Q(internal_sku__isnull=True) | Q(pk__in=Subquery(ids)))
