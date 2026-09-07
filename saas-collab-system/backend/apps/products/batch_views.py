"""Batch actions for product master data.

The normal SKU collection endpoint intentionally creates one SKU at a time.
This module contains the separate batch variant action used by the product
master page when an operator selects several colours and specification values.
All validation happens before the first row is written so a malformed batch
cannot leave a partially generated set behind.
"""

from itertools import product
from math import prod as math_prod

from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.ui_p5_scopes import filter_product_spus, require_create_scope

from .coding_services import build_sku_code
from .models import ProductCategory, ProductColor, ProductSKU, ProductSPU
from .permissions import IsProductMasterReadOrManage
from .serializers import ProductSKUSerializer


MAX_BATCH_COMBINATIONS = 200


def _dedupe_strings(value, *, field_name):
    """Normalize an input list of non-empty strings while preserving order."""

    if not isinstance(value, list):
        raise serializers.ValidationError({field_name: "必须是字符串数组。"})
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise serializers.ValidationError({field_name: "数组成员必须是字符串。"})
        item = item.strip()
        if not item:
            raise serializers.ValidationError({field_name: "数组成员不能为空。"})
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _normalize_batch_input(request_data):
    """Validate only the shape of the request and return normalized values."""

    if not hasattr(request_data, "get"):
        raise serializers.ValidationError("请求体必须是对象。")

    raw_spu = request_data.get("spu")
    if isinstance(raw_spu, bool):
        raise serializers.ValidationError({"spu": "SPU 必须是有效的整数 ID。"})
    if isinstance(raw_spu, int):
        spu_id = raw_spu
    elif isinstance(raw_spu, str) and raw_spu.strip().isdigit():
        spu_id = int(raw_spu.strip())
    else:
        raise serializers.ValidationError({"spu": "SPU 必须是有效的整数 ID。"})
    if spu_id < 1:
        raise serializers.ValidationError({"spu": "SPU 必须是有效的整数 ID。"})

    colors = _dedupe_strings(request_data.get("color_codes"), field_name="color_codes")
    if not colors:
        raise serializers.ValidationError({"color_codes": "至少选择一个颜色。"})

    raw_specs = request_data.get("spec_values", {})
    if raw_specs is None:
        raw_specs = {}
    if not isinstance(raw_specs, dict):
        raise serializers.ValidationError({"spec_values": "必须是按规格维度编码分组的对象。"})

    spec_values = {}
    for dimension, values in raw_specs.items():
        if not isinstance(dimension, str) or not dimension.strip():
            raise serializers.ValidationError({"spec_values": "规格维度编码必须是非空字符串。"})
        dimension = dimension.strip()
        spec_values[dimension] = _dedupe_strings(values, field_name=f"spec_values.{dimension}")

    return spu_id, colors, spec_values


def _category_dimensions(category):
    dimensions = category.spec_dimensions or []
    if not isinstance(dimensions, list):
        raise serializers.ValidationError({"spec_values": "商品分类的规格维度配置无效。"})
    codes = []
    for item in dimensions:
        if not isinstance(item, dict) or not item.get("code"):
            raise serializers.ValidationError({"spec_values": "商品分类的规格维度配置无效。"})
        code = str(item["code"]).strip()
        if not code or code in codes:
            raise serializers.ValidationError({"spec_values": "商品分类的规格维度配置无效。"})
        codes.append(code)
    return codes


def _resolve_spu(user, spu_id):
    """Get a locked, scope-filtered SPU and its locked category."""

    queryset = filter_product_spus(
        user,
        ProductSPU.objects.filter(tenant=user.tenant),
        "products.master.manage",
    )
    try:
        # Do not select_related the nullable category FK while locking.  On
        # PostgreSQL that would add an outer join to SELECT ... FOR UPDATE,
        # which the database rejects.  The category is locked separately
        # below.
        spu = queryset.select_for_update().get(pk=spu_id)
    except ProductSPU.DoesNotExist:
        # Keep hidden and cross-tenant SPUs indistinguishable from a missing
        # row.  DRF turns this validation into the normal 400 response below.
        raise serializers.ValidationError({"spu": "SPU 不存在或不在当前数据范围内。"})

    category_id = spu.category_node_id
    if not category_id:
        raise serializers.ValidationError({"spu": "SPU 未绑定结构化商品分类，无法生成 SKU。"})
    try:
        category = ProductCategory.objects.select_for_update().get(
            pk=category_id,
            tenant=user.tenant,
            is_active=True,
        )
    except ProductCategory.DoesNotExist:
        raise serializers.ValidationError({"spu": "SPU 的商品分类不存在或已停用。"})
    if category.level not in {ProductCategory.Level.L2, ProductCategory.Level.L3}:
        raise serializers.ValidationError({"spu": "SPU 必须绑定启用的末级分类。"})
    if category.children.exists():
        raise serializers.ValidationError({"spu": "SPU 必须绑定启用的末级分类。"})
    if category.level == ProductCategory.Level.L2:
        l1 = category.parent
        if (
            l1 is None
            or l1.level != ProductCategory.Level.L1
            or l1.tenant_id != user.tenant.id
            or not l1.is_active
        ):
            raise serializers.ValidationError({"spu": "SPU 必须绑定启用的末级分类。"})
    else:
        l2 = category.parent
        l1 = l2.parent if l2 is not None else None
        if (
            l2 is None
            or l1 is None
            or l2.level != ProductCategory.Level.L2
            or l1.level != ProductCategory.Level.L1
            or l2.tenant_id != user.tenant.id
            or l1.tenant_id != user.tenant.id
            or not l2.is_active
            or not l1.is_active
        ):
            raise serializers.ValidationError({"spu": "SPU 必须绑定启用的末级分类。"})
    return spu, category


def _validate_color_codes(tenant, color_codes):
    colors = list(
        ProductColor.objects.filter(
            tenant=tenant,
            code__in=color_codes,
            is_active=True,
        ).values_list("code", flat=True)
    )
    found = set(colors)
    invalid = [code for code in color_codes if code not in found]
    if invalid:
        raise serializers.ValidationError(
            {"color_codes": f"颜色不存在或已停用：{', '.join(invalid)}。"}
        )


def _build_combinations(category, spu, color_codes, spec_values):
    """Return deterministic (colour, spec mapping, predicted code) tuples."""

    dimension_codes = _category_dimensions(category)
    unknown = sorted(set(spec_values) - set(dimension_codes))
    if unknown:
        raise serializers.ValidationError(
            {"spec_values": f"未知规格维度：{', '.join(unknown)}。"}
        )

    # Missing dimensions and explicitly empty selections are intentionally
    # omitted from a combination.  build_sku_code fills missing dimensions
    # with its existing ``0`` placeholder, preserving single-SKU behaviour.
    selected_codes = [code for code in dimension_codes if spec_values.get(code)]
    selected_values = [spec_values[code] for code in selected_codes]
    specification_count = math_prod(len(values) for values in selected_values) if selected_values else 1
    total_count = len(color_codes) * specification_count
    if total_count > MAX_BATCH_COMBINATIONS:
        raise serializers.ValidationError(
            {"spec_values": f"一次最多生成 {MAX_BATCH_COMBINATIONS} 个 SKU。"}
        )
    # Materialize once because the Cartesian iterator must be reused for each
    # selected colour.
    spec_combinations = list(product(*selected_values)) if selected_values else [()]

    combinations = []
    seen_codes = set()
    for color_code in color_codes:
        for values in spec_combinations:
            current_specs = dict(zip(selected_codes, values))
            if dimension_codes:
                sku_code, _specification, _normalized = build_sku_code(
                    spu=spu,
                    color_code=color_code,
                    spec_values=current_specs,
                )
            else:
                # A category without dimensions has no ``0`` specification
                # segment.  This is the no-specification form used by the
                # product master generator.
                sku_code = f"{spu.spu_code}-{color_code}"
            if len(sku_code) > 80:
                raise serializers.ValidationError(
                    {"spec_values": f"生成的 SKU 编码长度不能超过 80：{sku_code}。"}
                )
            if sku_code in seen_codes:
                continue
            seen_codes.add(sku_code)
            combinations.append((color_code, current_specs, sku_code))

    if not combinations:
        raise serializers.ValidationError({"spec_values": "没有可生成的规格组合。"})
    return combinations


def _existing_skus_for_codes(tenant, sku_codes):
    return {
        item.sku_code: item
        for item in ProductSKU.objects.select_for_update().filter(
            tenant=tenant,
            sku_code__in=sku_codes,
        )
    }


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_batch_create(request):
    """Create a colour/specification Cartesian product for one SPU."""

    # New SKU creation has always required an all-tenant create scope.  Keep
    # that rule for batch generation as well, while the SPU lookup below still
    # applies the normal scoped-queryset boundary.
    require_create_scope(request.user, "products.master.manage")
    spu_id, color_codes, spec_values = _normalize_batch_input(request.data)

    with transaction.atomic():
        spu, category = _resolve_spu(request.user, spu_id)
        _validate_color_codes(request.user.tenant, color_codes)

        # build_sku_code expects the category through the SPU relation.  Keep
        # this locked category attached for all candidate calculations.
        spu.category_node = category
        combinations = _build_combinations(category, spu, color_codes, spec_values)
        candidate_codes = [item[2] for item in combinations]
        existing = _existing_skus_for_codes(request.user.tenant, candidate_codes)

        # A generated code belonging to another SPU indicates a data collision,
        # rather than an idempotent retry.  Reject the complete batch.
        conflicting = [
            code for code, item in existing.items() if item.spu_id != spu.id
        ]
        if conflicting:
            raise serializers.ValidationError(
                {"sku_code": f"SKU 编码已归属其他商品：{', '.join(sorted(conflicting))}。"}
            )

        created_items = []
        skipped = 0
        for color_code, current_specs, predicted_code in combinations:
            if predicted_code in existing:
                skipped += 1
                continue

            payload = {
                "spu": spu.id,
                "color_code": color_code,
                "spec_values": current_specs,
            }
            # A no-dimension category has no value for ProductSKUSerializer's
            # automatic specification builder, so supply its explicit code.
            if not _category_dimensions(category):
                payload["sku_code"] = predicted_code

            serializer = ProductSKUSerializer(
                data=payload,
                context={"request": request},
            )
            serializer.is_valid(raise_exception=True)
            try:
                # Use a savepoint so a concurrent single-SKU create's unique
                # collision does not poison the outer transaction.
                with transaction.atomic():
                    item = serializer.save(tenant=request.user.tenant)
            except IntegrityError:
                raced = ProductSKU.objects.select_for_update().filter(
                    tenant=request.user.tenant,
                    sku_code=predicted_code,
                ).first()
                if raced is not None and raced.spu_id == spu.id:
                    existing[predicted_code] = raced
                    skipped += 1
                    continue
                raise serializers.ValidationError(
                    {"sku_code": f"SKU 编码已归属其他商品：{predicted_code}。"}
                )
            if item.sku_code != predicted_code:
                # This should only be possible if the shared builder changes;
                # fail atomically instead of returning a misleading result.
                raise serializers.ValidationError(
                    {"sku_code": f"SKU 编码生成结果不一致：{predicted_code}。"}
                )
            existing[predicted_code] = item
            created_items.append(item)

        payload = {
            "created": len(created_items),
            "skipped": skipped,
            "total": len(combinations),
            "results": ProductSKUSerializer(created_items, many=True).data,
        }
        return success_response(payload, status=201 if created_items else 200)
