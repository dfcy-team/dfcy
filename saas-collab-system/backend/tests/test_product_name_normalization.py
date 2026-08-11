from io import StringIO

import pytest
from django.core.management import call_command

from apps.products.models import ProductColor, ProductLegacyItem, ProductSKU, ProductSPU
from apps.products.name_normalization import (
    consensus_spu_product_name,
    normalize_name_details,
    normalize_spu_product_name,
)
from apps.tenants.models import Tenant


@pytest.mark.parametrize(
    ("full_name", "color", "specification", "expected"),
    [
        ("Women's Dress - Black / M", "black", "M", "Women's Dress"),
        ("旅行收纳袋（蓝色，150cm×220cm）", "蓝色", "150cm×220cm", "旅行收纳袋"),
        ("T-Shirt (dark-blue) - M/XL", "dark-blue", "M/XL", "T-Shirt"),
        ("Storage Bin / white / 150 cm x 220 cm", "white", "150cm×220cm", "Storage Bin"),
    ],
)
def test_normalization_removes_only_explicit_color_and_specification(full_name, color, specification, expected):
    assert normalize_spu_product_name(full_name, color, specification) == expected


def test_normalization_does_not_remove_embedded_ordinary_word_and_is_idempotent():
    full_name = "Blackberry tea set"
    result = normalize_name_details(full_name, color_code="black", specification="XL")
    assert result.normalized == full_name
    assert result.reliable is False
    assert normalize_spu_product_name(result.normalized, "black", "XL") == full_name
    assert normalize_spu_product_name("蓝牙音箱", "blue", "") == "蓝牙音箱"


def test_group_consensus_strips_all_explicit_variants_when_row_fields_are_misaligned():
    rows = [
        # The color/spec columns are intentionally swapped relative to the
        # complete names, as observed in historical imports.
        {"product_name": "硬壶铃蓝色-10LB", "color_code": "pink", "specification": "1KG"},
        {"product_name": "硬壶铃粉色-1KG", "color_code": "blue", "specification": "10LB"},
    ]
    name, evidence = consensus_spu_product_name(rows, reference_name="硬壶铃粉色")
    assert name == "硬壶铃"
    assert evidence["support"] == 2
    assert evidence["color_terms"] >= 2
    assert evidence["specification_terms"] >= 2


def test_group_consensus_keeps_style_words_unless_explicit_specification():
    rows = [
        {"product_name": "枕套套装-红色-M", "color_code": "red", "specification": "M"},
        {"product_name": "枕套套装-蓝色-L", "color_code": "blue", "specification": "L"},
    ]
    name, _evidence = consensus_spu_product_name(rows, reference_name="枕套套装-红色")
    assert name == "枕套套装"

    explicit_style = [
        {"product_name": "脚凳-套装-黑色", "color_code": "black", "specification": "套装"},
    ]
    name, _evidence = consensus_spu_product_name(explicit_style, reference_name="脚凳-套装-黑色")
    assert name == "脚凳"


def test_group_consensus_skips_low_support_and_unrelated_reference():
    rows = [
        {"product_name": "硬壶铃蓝色-10LB", "color_code": "blue", "specification": "10LB"},
        {"product_name": "硬壶铃粉色-10LB", "color_code": "pink", "specification": "10LB"},
        {"product_name": "硬壶铃青色-10LB", "color_code": "cyan", "specification": "10LB"},
    ]
    name, evidence = consensus_spu_product_name(rows, reference_name="完全不同商品")
    assert name is None
    assert evidence["reason"] == "reference_name_unrelated"


def test_group_consensus_supports_color_alias_without_se_and_display_name_aliases():
    rows = [
        {"product_name": "凉感毯子-果绿-180*200", "color_code": "green", "specification": "180*200"},
        {"product_name": "凉感毯子-果绿色-200*220", "color_code": "green", "specification": "200*220"},
    ]
    name, _evidence = consensus_spu_product_name(
        rows,
        reference_name="凉感毯子-果绿",
        color_name_by_code={"green": "果绿"},
    )
    assert name == "凉感毯子"

    rows = [
        {"product_name": "床头罩-深灰-180", "color_code": "dark-gray", "specification": "180"},
        {"product_name": "床头罩-深灰色-200", "color_code": "dark-gray", "specification": "200"},
    ]
    name, _evidence = consensus_spu_product_name(rows, reference_name="床头罩-深灰")
    assert name == "床头罩"


def test_group_consensus_skips_residual_explicit_or_unconfirmed_variant_like_terms():
    rows = [
        {"product_name": "床垫-深灰-10cm", "color_code": "dark-gray", "specification": "180*200"},
        {"product_name": "床垫-深灰-10cm", "color_code": "dark-gray", "specification": "200*220"},
    ]
    name, evidence = consensus_spu_product_name(rows, reference_name="床垫-深灰")
    assert name is None
    assert evidence["reason"] == "unconfirmed_variant_like_term"



@pytest.mark.django_db
def test_repair_command_is_dry_run_by_default_and_only_updates_spu_name():
    tenant = Tenant.objects.create(name="Name repair tenant", code="name-repair")
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="SPU-NAME-1",
        legacy_spu_code="OLD-SPU-1",
        product_name="Travel Bag Black M",
    )
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-NAME-1")
    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-1",
        legacy_sku_code="OLD-SKU-1",
        product_name="Travel Bag Black M",
        color_code="black",
        specification="M",
        generated_spu=spu,
        generated_sku=sku,
    )

    output = StringIO()
    call_command("normalize_spu_product_names", stdout=output)
    spu.refresh_from_db()
    legacy.refresh_from_db()
    assert "mode=DRY-RUN" in output.getvalue()
    assert "PLAN" in output.getvalue()
    assert spu.product_name == "Travel Bag Black M"
    assert legacy.product_name == "Travel Bag Black M"
    assert ProductSKU.objects.get(pk=sku.pk).sku_code == "SKU-NAME-1"

    output = StringIO()
    call_command("normalize_spu_product_names", "--apply", stdout=output)
    spu.refresh_from_db()
    legacy.refresh_from_db()
    assert "mode=APPLY" in output.getvalue()
    assert spu.product_name == "Travel Bag"
    assert legacy.product_name == "Travel Bag Black M"
    assert ProductSKU.objects.get(pk=sku.pk).sku_code == "SKU-NAME-1"


@pytest.mark.django_db
def test_repair_command_uses_tenant_color_display_aliases_for_legacy_rows():
    tenant = Tenant.objects.create(name="Display alias tenant", code="display-alias")
    ProductColor.objects.create(tenant=tenant, code="green", name="果绿")
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="SPU-DISPLAY-1",
        legacy_spu_code="OLD-DISPLAY-1",
        product_name="凉感毯子-果绿",
    )
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-DISPLAY-1",
        legacy_sku_code="OLD-DISPLAY-SKU-1",
        product_name="凉感毯子-果绿-180*200",
        color_code="green",
        specification="180*200",
        generated_spu=spu,
    )
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-DISPLAY-1",
        legacy_sku_code="OLD-DISPLAY-SKU-2",
        product_name="凉感毯子-果绿色-200*220",
        color_code="green",
        specification="200*220",
        generated_spu=spu,
    )

    call_command("normalize_spu_product_names", "--apply", stdout=StringIO())
    spu.refresh_from_db()
    assert spu.product_name == "凉感毯子"
