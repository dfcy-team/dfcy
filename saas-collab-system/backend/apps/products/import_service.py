"""Incremental CSV import for the product detail bridge.

The product detail page exposes two kinds of records: staged legacy rows and
already generated SKU rows.  This module keeps the import rules in one place
so that a CSV can update either record without accidentally creating a new SKU
or crossing a tenant boundary.

Import semantics are intentionally conservative:

* ``auto`` updates an exact match and creates a pending legacy row when only a
  new legacy SKU is supplied.
* ``create`` only creates a pending legacy row; any existing exact match is an
  error.
* ``update`` requires an exact existing legacy or new SKU match.
* A new SKU code is a lookup key, never a request to allocate a SKU.  An
  unknown new SKU is therefore always an error.
* Missing columns and blank cells are no-ops.  There is no implicit clearing
  operation in CSV imports.

Each row runs in its own transaction.  A malformed row cannot partially write
the staged legacy item or its generated SKU counterpart.
"""

from __future__ import annotations

import csv
import io
import re
import time
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from apps.permissions.ui_p5_scopes import filter_product_skus

from .models import ProductCategory, ProductLegacyItem, ProductSKU


MODES = {"auto", "create", "update"}

FIELD_ALIASES = {
    "legacy_spu_code": ("旧SPU编码", "old_spu_code", "legacy_spu_code"),
    "legacy_sku_code": ("旧SKU编码", "旧SKU", "old_sku_code", "legacy_sku_code"),
    "sku_code": ("新SKU编码", "新SKU", "sku_code", "new_sku_code"),
    "product_name": ("商品名称", "商品名", "product_name", "sku_product_name"),
    "category_code": ("完整类目编码", "分类编码", "category_code"),
    "attribute_code": ("属性码", "属性编码", "attribute_code"),
    "color_code": ("颜色英文编码", "颜色", "颜色编码", "color_code"),
    "specification": ("规格", "specification"),
    "purchase_price": ("采购价格", "采购价", "purchase_price", "purchase_cost"),
    "unit": ("单位", "unit"),
    "image_url": ("商品图片", "商品图片 URL", "图片URL", "图片 URL", "图片地址", "image_url", "image"),
    "package_weight": ("重量(g)", "重量（g）", "重量", "package_weight", "weight_g"),
    "package_volume": ("体积(m³)", "体积(m3)", "体积", "package_volume", "volume_m3"),
    "package_length_cm": ("长(cm)", "长（cm）", "长度", "package_length_cm", "length_cm"),
    "package_width_cm": ("宽(cm)", "宽（cm）", "宽度", "package_width_cm", "width_cm"),
    "package_height_cm": ("高(cm)", "高（cm）", "高度", "package_height_cm", "height_cm"),
    "origin_country": ("原产国", "原产地", "origin_country", "country_of_origin"),
    "hs_code": ("HS编码", "HS码", "hs_code", "hs"),
    "product_description": ("商品描述", "描述", "product_description", "description"),
    "is_active": ("商品状态", "SKU状态", "状态", "is_active", "sku_status"),
}

TEXT_LIMITS = {
    "legacy_spu_code": 120,
    "legacy_sku_code": 160,
    "sku_code": 80,
    "product_name": 200,
    "color_code": 40,
    "specification": 120,
    "unit": 30,
    "image_url": 500,
    "origin_country": 80,
    "hs_code": 20,
}

DECIMAL_SPECS = {
    "purchase_price": (14, 4),
    "package_weight": (10, 3),
    "package_volume": (12, 6),
    "package_length_cm": (10, 3),
    "package_width_cm": (10, 3),
    "package_height_cm": (10, 3),
}

DETAIL_FIELDS = {
    "product_name",
    "purchase_price",
    "unit",
    "image_url",
    "package_weight",
    "package_volume",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "origin_country",
    "hs_code",
    "product_description",
}
VARIANT_FIELDS = {"category_code", "attribute_code", "color_code", "specification"}


class ImportRowError(ValueError):
    """A user-correctable error for one CSV row."""


def _normalise_header(value):
    return str(value or "").replace("\ufeff", "").strip()


def _header_lookup(fieldnames):
    return {_normalise_header(name) for name in (fieldnames or []) if _normalise_header(name)}


def _row_value(row, key):
    for alias in FIELD_ALIASES[key]:
        raw = row.get(alias)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return ""


def _has_column(headers, key):
    return any(alias in headers for alias in FIELD_ALIASES[key])


def _validate_text(value, key):
    if not value:
        return ""
    limit = TEXT_LIMITS.get(key)
    if limit and len(value) > limit:
        raise ImportRowError(f"{key} 长度不能超过 {limit} 个字符。")
    return value


def _parse_decimal(raw, key):
    if not raw:
        return None
    try:
        value = Decimal(str(raw).replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ImportRowError(f"{key} 必须是非负数字：{raw}")
    if not value.is_finite() or value < 0:
        raise ImportRowError(f"{key} 必须是非负数字：{raw}")
    max_digits, decimal_places = DECIMAL_SPECS[key]
    exponent = value.as_tuple().exponent
    scale = max(0, -exponent)
    integer_digits = max(value.adjusted() + 1, 1) if value else 1
    if scale > decimal_places or integer_digits + scale > max_digits:
        raise ImportRowError(
            f"{key} 超出精度限制（最多 {max_digits} 位，{decimal_places} 位小数）：{raw}"
        )
    return value


def _parse_status(raw):
    if not raw:
        return None
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().casefold()
    if value in {"true", "1", "active", "on_sale", "on sale", "在售", "启用"}:
        return True
    if value in {"false", "0", "inactive", "off_sale", "off sale", "下架", "停用"}:
        return False
    raise ImportRowError("商品状态只能填写在售/下架（或启用/停用）。")


def _validate_image_url(value):
    if not value:
        return value
    if (value.startswith("/media/product-images/") and ".." not in value.split("/")) or re.fullmatch(
        r"https?://[^\s]+", value, flags=re.IGNORECASE
    ):
        return value
    raise ImportRowError("image_url 必须是 http(s) URL 或 /media/product-images/ URL。")


def _validate_hs_code(value):
    if not value:
        return value
    if len(value) < 2 or len(value) > 20 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\- ]*", value):
        raise ImportRowError(f"HS编码格式无效：{value}")
    return value


def _parse_row(row, headers, line_no):
    """Build a sparse, validated row mapping.

    A key is present in the returned mapping only when its column exists and
    contains a non-empty value.  This is what makes a partial follow-up CSV
    safe: omitted columns and blank cells leave the stored value untouched.
    """

    parsed = {"line": line_no}
    for key in FIELD_ALIASES:
        if not _has_column(headers, key):
            continue
        value = _row_value(row, key)
        if not value:
            continue
        if key in TEXT_LIMITS:
            value = _validate_text(value, key)
        if key == "color_code":
            value = value.lower()
        parsed[key] = value

    if "attribute_code" in parsed:
        if not re.fullmatch(r"[0-9]", parsed["attribute_code"]):
            raise ImportRowError(f"属性码必须为空或 1 位数字：{parsed['attribute_code']}")

    for key in DECIMAL_SPECS:
        if key in parsed:
            parsed[key] = _parse_decimal(parsed[key], key)

    if "image_url" in parsed:
        parsed["image_url"] = _validate_image_url(parsed["image_url"])
    if "hs_code" in parsed:
        parsed["hs_code"] = _validate_hs_code(parsed["hs_code"])
    if "is_active" in parsed:
        parsed["is_active"] = _parse_status(parsed["is_active"])
    return parsed


def _active_categories(tenant):
    return list(
        ProductCategory.objects.filter(tenant=tenant, level__in=(2, 3), is_active=True).select_related("parent__parent")
    )


def _resolve_category(categories, code):
    if not code:
        return None
    category = next(
        (
            item
            for item in categories
            if item.parent_id
            and (
                (item.level == ProductCategory.Level.L2 and f"{item.parent.code}{item.code}" == code)
                or (
                    item.level == ProductCategory.Level.L3
                    and item.parent.parent_id
                    and f"{item.parent.parent.code}{item.parent.code}{item.code}" == code
                )
            )
        ),
        None,
    )
    if category is None:
        matches = [item for item in categories if item.code == code]
        category = matches[0] if len(matches) == 1 else None
    if category is None:
        raise ImportRowError(f"未找到有效的完整类目编码：{code}")
    # The category list is loaded once to resolve the user-facing composite
    # code, but a large import can keep processing it for several seconds.
    # Re-read and lock the selected path inside the row transaction so a
    # category (or one of its parents) cannot be disabled between lookup and
    # persistence.
    locked = (
        ProductCategory.objects.select_for_update(of=("self",))
        .filter(pk=category.pk, tenant_id=category.tenant_id, is_active=True)
        .first()
    )
    if locked is None:
        raise ImportRowError(f"未找到有效的完整类目编码：{code}")

    parent = None
    grandparent = None
    if locked.parent_id:
        parent = (
            ProductCategory.objects.select_for_update(of=("self",))
            .filter(pk=locked.parent_id, tenant_id=locked.tenant_id, is_active=True)
            .first()
        )
    if parent is not None and parent.parent_id:
        grandparent = (
            ProductCategory.objects.select_for_update(of=("self",))
            .filter(pk=parent.parent_id, tenant_id=locked.tenant_id, is_active=True)
            .first()
        )
    current_full_code = None
    valid_path = (
        locked.level == ProductCategory.Level.L2
        and parent is not None
        and parent.level == ProductCategory.Level.L1
    ) or (
        locked.level == ProductCategory.Level.L3
        and parent is not None
        and parent.level == ProductCategory.Level.L2
        and grandparent is not None
        and grandparent.level == ProductCategory.Level.L1
    )
    if locked.level == ProductCategory.Level.L2 and parent is not None:
        current_full_code = f"{parent.code}{locked.code}"
    elif locked.level == ProductCategory.Level.L3 and parent is not None and grandparent is not None:
        current_full_code = f"{grandparent.code}{parent.code}{locked.code}"
    simple_code_is_unique = (
        code == locked.code
        and ProductCategory.objects.filter(
            tenant_id=locked.tenant_id,
            level__in=(ProductCategory.Level.L2, ProductCategory.Level.L3),
            code=code,
            is_active=True,
        ).count()
        == 1
    )
    if not valid_path or (code != current_full_code and not simple_code_is_unique):
        raise ImportRowError(f"未找到有效的完整类目编码：{code}")
    return locked


def _variant_value(item, field):
    if field == "category_code":
        category = getattr(item, "category_node", None)
        if category is None and hasattr(item, "spu"):
            category = getattr(item.spu, "category_node", None)
        if category is None:
            return None
        if category.level == ProductCategory.Level.L2:
            return f"{category.parent.code}{category.code}" if category.parent_id else category.code
        if category.level == ProductCategory.Level.L3 and category.parent and category.parent.parent_id:
            return f"{category.parent.parent.code}{category.parent.code}{category.code}"
        return category.code
    if field == "attribute_code":
        return getattr(item, "attribute_code", None) or getattr(getattr(item, "spu", None), "season_code", None) or "0"
    if field == "color_code":
        return getattr(item, "color_code", None)
    return getattr(item, "specification", None)


def _check_variant_immutable(item, parsed, category):
    for field in VARIANT_FIELDS:
        if field not in parsed:
            continue
        incoming = category if field == "category_code" else parsed[field]
        if field == "category_code":
            current = getattr(item, "category_node", None)
            if current is None and hasattr(item, "spu"):
                current = getattr(item.spu, "category_node", None)
            if current is None or current.pk != incoming.pk:
                raise ImportRowError("已生成 SKU 的分类不可通过导入修改。")
            continue
        current = _variant_value(item, field) or ""
        if str(current).casefold() != str(incoming).casefold():
            labels = {
                "attribute_code": "属性码",
                "color_code": "颜色",
                "specification": "规格",
            }
            raise ImportRowError(f"已生成 SKU 的{labels[field]}不可通过导入修改。")


def _check_spu_identity(spu, parsed):
    if spu is None:
        return
    if "legacy_spu_code" in parsed and parsed["legacy_spu_code"] != (spu.legacy_spu_code or ""):
        raise ImportRowError("已匹配 SKU 的旧 SPU 编码不可通过导入修改。")


def _editable_values(parsed):
    return {field: parsed[field] for field in DETAIL_FIELDS if field in parsed}


def _apply_values(instance, values):
    changed = []
    for field, value in values.items():
        if getattr(instance, field) != value:
            setattr(instance, field, value)
            changed.append(field)
    if changed:
        instance.save(update_fields=[*changed, "updated_at"])
    return bool(changed)


def _apply_legacy(item, parsed, category):
    is_generated = bool(item.generated_sku_id)
    if item.generated_spu_id and (
        item.generated_spu is None or item.generated_spu.tenant_id != item.tenant_id
    ):
        raise ImportRowError("生成商品关系不属于当前租户，拒绝跨租户更新。")
    if is_generated:
        if (
            item.generated_spu is None
            or item.generated_spu.tenant_id != item.tenant_id
            or item.generated_sku is None
            or item.generated_sku.tenant_id != item.tenant_id
        ):
            raise ImportRowError("生成商品关系不属于当前租户，拒绝跨租户更新。")
        _check_variant_immutable(item, parsed, category)
        _check_spu_identity(item.generated_spu, parsed)
    else:
        if "is_active" in parsed:
            raise ImportRowError("尚未生成 SKU 的记录不能修改商品状态。")

    values = _editable_values(parsed)
    # Variant fields are staged on the legacy row only until generation.
    if not is_generated:
        if category is not None:
            values["category_node"] = category
        for field in ("attribute_code", "color_code", "specification", "legacy_spu_code"):
            if field in parsed:
                values[field] = parsed[field]
    else:
        # Never mutate generated identity fields, even when the values happen
        # to be equal.  This also makes update_fields deterministic.
        values.pop("legacy_spu_code", None)

    changed = _apply_values(item, values)
    if item.status == ProductLegacyItem.Status.ERROR and changed:
        item.status = ProductLegacyItem.Status.PENDING
        item.error_message = ""
        item.save(update_fields=["status", "error_message", "updated_at"])
        changed = True

    if is_generated:
        sku = ProductSKU.objects.select_for_update(of=("self",)).select_related("spu", "spu__category_node").get(
            pk=item.generated_sku_id, tenant=item.tenant_id
        )
        sku_values = _editable_values(parsed)
        sku_changed = _apply_values(sku, sku_values)
        if "is_active" in parsed and sku.is_active != parsed["is_active"]:
            sku.is_active = parsed["is_active"]
            sku.save(update_fields=["is_active", "updated_at"])
            sku_changed = True
        return changed or sku_changed
    return changed


def _apply_sku(sku, parsed, category, legacy_item=None):
    if sku.tenant_id != sku.spu.tenant_id:
        raise ImportRowError("商品所属关系不属于当前租户，拒绝跨租户更新。")
    _check_variant_immutable(sku, parsed, category)
    _check_spu_identity(sku.spu, parsed)
    if legacy_item is not None:
        if (
            "legacy_sku_code" in parsed
            and parsed["legacy_sku_code"] != legacy_item.legacy_sku_code
        ):
            raise ImportRowError("旧 SKU 和新 SKU 编码未指向同一条商品记录。")
        # A new-SKU lookup may also carry its generated legacy bridge.  Apply
        # through the bridge so the two views retain the same physical data.
        return _apply_legacy(legacy_item, parsed, category)

    values = _editable_values(parsed)
    if "legacy_sku_code" in parsed:
        current = sku.legacy_sku_code or ""
        if current and current != parsed["legacy_sku_code"]:
            raise ImportRowError("新 SKU 已绑定其他旧 SKU 编码。")
        if not current:
            values["legacy_sku_code"] = parsed["legacy_sku_code"]
    changed = _apply_values(sku, values)
    if "is_active" in parsed and sku.is_active != parsed["is_active"]:
        sku.is_active = parsed["is_active"]
        sku.save(update_fields=["is_active", "updated_at"])
        changed = True
    return changed


def _scope_queryset(user, queryset):
    """Apply the same SKU data-scope boundary used by product detail views."""

    return filter_product_skus(user, queryset, "products.master.manage")


def _find_targets(user, tenant, parsed):
    old_code = parsed.get("legacy_sku_code", "")
    new_code = parsed.get("sku_code", "")
    legacy = None
    old_sku = None
    new_sku = None
    if old_code:
        legacy = (
            ProductLegacyItem.objects.select_for_update(of=("self",))
            .select_related("generated_spu", "generated_sku", "category_node")
            .filter(tenant=tenant, legacy_sku_code=old_code)
            .first()
        )
        # The custom-scope helper adds ``distinct()``. Resolve visible IDs
        # first, then lock the base SKU rows in a separate non-DISTINCT query;
        # PostgreSQL does not permit ``FOR UPDATE`` on DISTINCT selects.
        visible_old_sku_ids = list(
            _scope_queryset(
                user,
                ProductSKU.objects.filter(tenant=tenant, spu__tenant=tenant, legacy_sku_code=old_code)
                .order_by("pk"),
            ).values_list("pk", flat=True)[:2]
        )
        old_skus = list(
            ProductSKU.objects.select_for_update(of=("self",))
            .select_related("spu", "spu__category_node")
            .filter(tenant=tenant, spu__tenant=tenant, pk__in=visible_old_sku_ids)
            .order_by("pk")
        )
        if len(old_skus) > 1:
            raise ImportRowError("旧 SKU 编码匹配到多条商品记录，无法确定更新目标。")
        old_sku = old_skus[0] if old_skus else None
    if new_code:
        visible_new_sku_id = (
            _scope_queryset(
                user,
                ProductSKU.objects.filter(tenant=tenant, spu__tenant=tenant, sku_code=new_code),
            )
            .values_list("pk", flat=True)
            .first()
        )
        if visible_new_sku_id is not None:
            new_sku = (
                ProductSKU.objects.select_for_update(of=("self",))
                .select_related("spu", "spu__category_node")
                .filter(tenant=tenant, spu__tenant=tenant, pk=visible_new_sku_id)
                .first()
            )
    return legacy, old_sku, new_sku


def _process_row(user, tenant, parsed, mode, categories):
    legacy, old_sku, new_sku = _find_targets(user, tenant, parsed)
    old_code = parsed.get("legacy_sku_code", "")
    new_code = parsed.get("sku_code", "")

    if new_code and new_sku is None:
        raise ImportRowError("新 SKU 编码不存在，导入不会自动创建 SKU。")
    if old_sku is not None and new_sku is not None and old_sku.pk != new_sku.pk:
        raise ImportRowError("旧 SKU 和新 SKU 编码未指向同一条商品记录。")
    sku = new_sku or old_sku
    if legacy is not None and sku is not None:
        if legacy.generated_sku_id != sku.pk:
            raise ImportRowError("旧 SKU 和新 SKU 编码未指向同一条商品记录。")
    matched = legacy is not None or sku is not None

    if mode == "create" and matched:
        raise ImportRowError("编码已存在，新增模式不能覆盖已有商品。")
    if mode == "update" and not matched:
        raise ImportRowError("更新模式要求旧 SKU 或新 SKU 编码已存在。")

    category = _resolve_category(categories, parsed.get("category_code")) if "category_code" in parsed else None

    if not matched:
        # A new SKU key was already rejected above.  Only a legacy key can
        # create a staged row; generation remains an explicit user action.
        if not old_code and mode != "create":
            raise ImportRowError("新增旧商品必须填写旧 SKU 编码。")
        if not parsed.get("product_name"):
            raise ImportRowError("新增旧商品必须填写商品名称。")
        if "is_active" in parsed:
            raise ImportRowError("尚未生成 SKU 的记录不能修改商品状态。")
        values = _editable_values(parsed)
        values["legacy_sku_code"] = old_code or None
        values["legacy_spu_code"] = parsed.get("legacy_spu_code", "")
        if category is not None:
            values["category_node"] = category
        values["attribute_code"] = parsed.get("attribute_code", "0")
        for field in ("color_code", "specification"):
            if field in parsed:
                values[field] = parsed[field]
        values.setdefault("unit", "件")
        values["tenant"] = tenant
        values["status"] = ProductLegacyItem.Status.PENDING
        values["error_message"] = ""
        item = ProductLegacyItem.objects.create(**values)
        return "created", item.pk

    if legacy is not None:
        changed = _apply_legacy(legacy, parsed, category)
        # When both keys match, _apply_legacy already updates the generated
        # SKU.  If the row is pending there is no SKU to update yet.
        return ("updated", None) if changed else ("unchanged", None)

    bridge = (
        ProductLegacyItem.objects.select_for_update(of=("self",))
        .select_related("generated_spu", "generated_sku", "category_node")
        .filter(tenant=tenant, generated_sku_id=sku.pk)
        .first()
    )
    changed = _apply_sku(sku, parsed, category, legacy_item=bridge)
    return ("updated", None) if changed else ("unchanged", None)


def import_legacy_product_items(*, request, csv_text, mode="auto"):
    """Import CSV rows and return ``(summary, http_status)``.

    Permission checks remain in ``product_legacy_collection``.  This service
    additionally scopes every new-SKU lookup to the authenticated tenant and
    product-master data scope.
    """

    mode = str(mode or "auto").strip().lower()
    if mode not in MODES:
        raise ValueError("导入模式只能是 auto、create 或 update。")
    if not str(csv_text or "").strip():
        raise ValueError("请选择包含商品数据的 CSV 文件。")

    reader = csv.DictReader(io.StringIO(str(csv_text).lstrip("\ufeff")))
    headers = _header_lookup(reader.fieldnames)
    if not _has_column(headers, "legacy_sku_code") and not _has_column(headers, "sku_code"):
        raise ValueError("CSV 必须包含旧SKU编码或新SKU编码列。")

    started_at = time.monotonic()
    categories = _active_categories(request.user.tenant)
    tenant = request.user.tenant
    created = updated = unchanged = skipped = generated = 0
    created_ids = []
    errors = []
    seen = set()
    rows_seen = 0

    for line_no, raw_row in enumerate(reader, 2):
        rows_seen += 1
        row = {_normalise_header(key): value for key, value in raw_row.items() if key is not None}
        try:
            parsed = _parse_row(row, headers, line_no)
            old_code = parsed.get("legacy_sku_code", "")
            new_code = parsed.get("sku_code", "")
            duplicate_keys = [key for key in (("legacy", old_code), ("sku", new_code)) if key[1]]
            if any(key in seen for key in duplicate_keys):
                raise ImportRowError("CSV 内存在重复的商品编码，未重复处理该行。")
            seen.update(duplicate_keys)
            if mode != "create" and not duplicate_keys:
                raise ImportRowError("旧SKU编码和新SKU编码至少填写一个。")
            with transaction.atomic():
                outcome = _process_row(request.user, tenant, parsed, mode, categories)
            outcome_name, outcome_id = outcome
            if outcome_name == "created":
                created += 1
                if outcome_id and not duplicate_keys:
                    created_ids.append(outcome_id)
            elif outcome_name == "updated":
                updated += 1
            else:
                unchanged += 1
        except (ImportRowError, IntegrityError, ProductCategory.DoesNotExist) as exc:
            skipped += 1
            message = str(exc) or "导入行保存失败。"
            if isinstance(exc, IntegrityError):
                message = "商品编码已存在或与其他记录冲突。"
            errors.append({"line": line_no, "message": message})
        except Exception as exc:
            # Keep row-level atomicity even for a model validation/database
            # error that is not one of the expected user-facing validators.
            skipped += 1
            errors.append({"line": line_no, "message": str(exc) or "导入行保存失败。"})

    if rows_seen == 0:
        raise ValueError("CSV 中没有可导入的数据行。")
    return (
        {
            "mode": mode,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped": skipped,
            "generated": generated,
            "created_ids": created_ids,
            "processed": created + updated + unchanged + skipped,
            "error_count": len(errors),
            "errors": errors,
            "duration_ms": round((time.monotonic() - started_at) * 1000),
        },
        201 if created else 200,
    )
