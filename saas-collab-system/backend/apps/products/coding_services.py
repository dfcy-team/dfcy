import re

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ProductCategory, ProductCodeSequence, ProductSPU


SEASONS = (
    {"code": "1", "name": "春", "english_name": "Spring"},
    {"code": "2", "name": "夏", "english_name": "Summer"},
    {"code": "3", "name": "秋", "english_name": "Autumn"},
    {"code": "4", "name": "冬", "english_name": "Winter"},
    {"code": "5", "name": "春秋", "english_name": "Spring & Autumn"},
)
SEASON_CODES = {item["code"] for item in SEASONS}
SPEC_VALUE_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:cm|mm|kg|g|lb|lbs|oz|m|ft|inch)$", re.IGNORECASE)


def is_valid_specification_value(value):
    return bool(str(value or "").strip())


def category_path(category):
    if category.level == ProductCategory.Level.L3 and category.parent_id and category.parent.parent_id:
        l2 = category.parent
        return l2.parent, l2, category
    if category.level == ProductCategory.Level.L2 and category.parent_id:
        return category.parent, category, None
    raise ValidationError("SPU must use an L2 or L3 product category.")


@transaction.atomic
def allocate_spu_code(*, tenant, category, season_code):
    if category.tenant_id != tenant.id or not category.is_active:
        raise ValidationError("Category must be active and belong to the current tenant.")
    if not re.fullmatch(r"[0-9]", str(season_code or "")):
        raise ValidationError("Attribute code must be one digit.")
    l1, l2, l3 = category_path(category)
    l3_code = l3.code if l3 else ""
    sequence, _ = ProductCodeSequence.objects.select_for_update().get_or_create(
        tenant=tenant,
        l1_code=l1.code,
        l2_code=l2.code,
        l3_code=l3_code,
        season_code=season_code,
        defaults={"current_value": 0},
    )
    next_value = sequence.current_value + 1
    if next_value > 999:
        raise ValidationError("This category and attribute has exhausted its 001-999 SPU sequence.")
    sequence.current_value = next_value
    sequence.save(update_fields=["current_value", "updated_at"])
    return f"{l1.code}{l2.code}{l3_code}{season_code}{next_value:03d}", (l1.code, l2.code, l3_code)


def build_specification(category, spec_values):
    dimensions = category.spec_dimensions or []
    if not isinstance(spec_values, dict):
        raise ValidationError("spec_values must be an object keyed by dimension code.")
    if not dimensions:
        if any(str(value or "").strip() not in ("", "0") for value in spec_values.values()):
            raise ValidationError("This category has no configured specifications.")
        return "", {}
    expected = [item.get("code") for item in dimensions]
    if any(not code for code in expected) or len(set(expected)) != len(expected):
        raise ValidationError("Category specification dimensions are invalid.")
    extra = set(spec_values) - set(expected)
    if extra:
        raise ValidationError(f"Unknown specification dimensions: {', '.join(sorted(extra))}.")
    values = []
    normalized = {}
    for dimension in dimensions:
        code = dimension["code"]
        value = str(spec_values.get(code, "")).strip()
        if value in ("", "0"):
            continue
        configured_values = dimension.get("values") or []
        if configured_values and value not in configured_values:
            raise ValidationError(f"Specification value for {code} is not configured for this category.")
        if not is_valid_specification_value(value):
            raise ValidationError(f"Specification value for {code} cannot be empty.")
        normalized[code] = value
        values.append(value)
    return "×".join(values), normalized


def build_sku_code(*, spu, color_code, spec_values):
    if not spu.category_node_id:
        raise ValidationError("SPU has no structured category; SKU code cannot be generated automatically.")
    specification, normalized = build_specification(spu.category_node, spec_values)
    suffix = f"-{specification}" if specification else ""
    return f"{spu.spu_code}-{color_code}{suffix}", specification, normalized
