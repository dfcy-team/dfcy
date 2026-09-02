import hashlib
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ProductCategory, ProductCodeSequence, ProductSKU, ProductSPU


SEASONS = (
    {"code": "1", "name": "春", "english_name": "Spring"},
    {"code": "2", "name": "夏", "english_name": "Summer"},
    {"code": "3", "name": "秋", "english_name": "Autumn"},
    {"code": "4", "name": "冬", "english_name": "Winter"},
    {"code": "5", "name": "春秋", "english_name": "Spring & Autumn"},
)
SEASON_CODES = {item["code"] for item in SEASONS}
SPEC_VALUE_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:cm|mm|kg|m|inch)$", re.IGNORECASE)
SKU_CODE_MAX_LENGTH = 80


def category_path(category):
    if category.level != ProductCategory.Level.L3 or not category.parent_id or not category.parent.parent_id:
        raise ValidationError("SPU must use a complete L1/L2/L3 leaf category.")
    l2 = category.parent
    l1 = l2.parent
    return l1, l2, category


@transaction.atomic
def allocate_spu_code(*, tenant, category, season_code):
    if category.tenant_id != tenant.id or not category.is_active:
        raise ValidationError("Category must be active and belong to the current tenant.")
    if season_code not in SEASON_CODES:
        raise ValidationError("Unsupported season code.")
    l1, l2, l3 = category_path(category)
    sequence, _ = ProductCodeSequence.objects.select_for_update().get_or_create(
        tenant=tenant,
        l1_code=l1.code,
        l2_code=l2.code,
        l3_code=l3.code,
        season_code=season_code,
        defaults={"current_value": 0},
    )
    next_value = sequence.current_value + 1
    if next_value > 999:
        raise ValidationError("This category and season has exhausted its 001-999 SPU sequence.")
    sequence.current_value = next_value
    sequence.save(update_fields=["current_value", "updated_at"])
    return f"{l1.code}{l2.code}{l3.code}{season_code}{next_value:03d}", (l1.code, l2.code, l3.code)


def build_specification(category, spec_values):
    dimensions = category.spec_dimensions or []
    if not dimensions:
        raise ValidationError("The selected L3 category has no specification dimensions configured.")
    if not isinstance(spec_values, dict):
        raise ValidationError("spec_values must be an object keyed by dimension code.")
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
        value = str(spec_values.get(code, "0")).strip()
        if value != "0" and not SPEC_VALUE_PATTERN.fullmatch(value):
            raise ValidationError(f"Specification value for {code} must include a supported unit.")
        normalized[code] = value
        values.append(value)
    return "×".join(values), normalized


def build_sku_code(*, spu, color_code, spec_values):
    if not spu.category_node_id:
        raise ValidationError("SPU has no structured category; SKU code cannot be generated automatically.")
    specification, normalized = build_specification(spu.category_node, spec_values)
    return f"{spu.spu_code}-{color_code}-{specification}", specification, normalized


def allocate_legacy_sku_code(*, tenant, base_code, legacy_sku_code, max_length=SKU_CODE_MAX_LENGTH):
    """Return a unique, stable code for an imported legacy SKU.

    The regular generated code remains untouched when it fits the column and
    is not already occupied.  Legacy imports can contain multiple old SKUs
    with the same colour/specification, however, so a colliding (or too long)
    base receives a deterministic ``-L<sha256>`` suffix derived from the old
    SKU.  The suffix is retried with a deterministic counter only for the
    exceedingly unlikely case that an existing row already owns that value.
    This keeps different legacy rows separate and makes a retry produce the
    same candidate after the first row has been persisted.
    """

    base_code = str(base_code or "")
    legacy_sku_code = str(legacy_sku_code or "").strip()
    if not legacy_sku_code:
        # This helper is only for legacy generation.  Keep direct/non-legacy
        # SKU behaviour unchanged while still protecting the DB column when a
        # caller explicitly opts into this helper.
        return base_code[:max_length]

    def available(candidate):
        return not ProductSKU.objects.filter(tenant=tenant, sku_code=candidate).exists()

    if len(base_code) <= max_length and available(base_code):
        return base_code

    # The first candidate is the production backfill format: it is short,
    # deterministic, and independent of row ordering.
    for attempt in range(1000):
        seed = legacy_sku_code if attempt == 0 else f"{legacy_sku_code}:{attempt}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()
        suffix = f"-L{digest}"
        prefix_length = max(0, max_length - len(suffix))
        candidate = f"{base_code[:prefix_length]}{suffix}"
        if available(candidate):
            return candidate

    raise ValueError("Unable to allocate a unique legacy SKU code.")
