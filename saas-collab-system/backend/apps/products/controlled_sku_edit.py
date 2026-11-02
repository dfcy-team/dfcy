"""Preview and confirm a tightly scoped SKU identity correction."""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .coding_services import build_sku_code
from .models import ProductColor, ProductSKU, ProductSKUAlias, ProductSPU, ProductLegacyItem
from .sku_aliases import code_key
from .sku_alias_views import create_alias


def _plan(tenant, sku, data, allowed_spu_ids=None):
    spu = ProductSPU.objects.filter(tenant=tenant, pk=data.get("spu_id")).first()
    if not spu:
        raise ValidationError({"spu_id": "请选择当前租户内有效的 SPU。"})
    if spu.product_type != sku.spu.product_type:
        raise ValidationError({"spu_id": "只能调整到相同类型的 SPU。"})
    if allowed_spu_ids is not None and spu.pk not in allowed_spu_ids:
        raise ValidationError({"spu_id": "目标 SPU 不在当前数据范围内。"})
    if spu.is_code_frozen:
        raise ValidationError({"spu_id": "目标 SPU 编码已冻结，不能调整 SKU 归属。"})
    if sku.is_code_frozen or sku.spu.is_code_frozen:
        raise ValidationError({"sku": "SKU 或原 SPU 编码已冻结，不能修改。"})
    color = str(data.get("color_code", "")).strip()
    if color and not ProductColor.objects.filter(tenant=tenant, code=color, is_active=True).exists():
        raise ValidationError({"color_code": "颜色必须来自当前租户的有效颜色字典。"})
    specs = data.get("spec_values", {})
    if spu.category_node_id:
        new_code, specification, normalized = build_sku_code(spu=spu, color_code=color, spec_values=specs)
    else:
        raise ValidationError({"spu_id": "目标 SPU 缺少结构化分类，无法按规则生成 SKU 编码。"})
    old_alias = str(data.get("legacy_sku_code", "")).strip()
    if len(old_alias) > 160 or "\x00" in old_alias:
        raise ValidationError({"legacy_sku_code": "旧 SKU 编码无效。"})
    if not old_alias:
        old_alias = sku.sku_code
    if len(new_code) > 80:
        raise ValidationError({"sku_code": "生成的 SKU 编码超过 80 个字符。"})
    return {"spu": spu, "color": color, "specs": normalized, "specification": specification,
            "sku_code": new_code, "legacy": old_alias}


def preview_controlled_edit(tenant, sku, data, allowed_spu_ids=None, actor=None):
    plan = _plan(tenant, sku, data, allowed_spu_ids)
    collision = (ProductSKU.objects.filter(tenant=tenant).exclude(pk=sku.pk).filter(Q(sku_code=plan["sku_code"]) | Q(legacy_sku_code=plan["sku_code"])).exists()
                 or ProductSKUAlias.objects.filter(tenant=tenant, code_key=code_key(plan["sku_code"])).exclude(sku=sku).exists()
                 or ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code=plan["sku_code"]).exclude(generated_sku=sku).exists())
    alias_collision = ProductSKUAlias.objects.filter(tenant=tenant, code_key=code_key(plan["legacy"])).exclude(sku=sku).exists()
    current_collision = ProductSKU.objects.filter(tenant=tenant).exclude(pk=sku.pk).filter(Q(sku_code=plan["legacy"]) | Q(legacy_sku_code=plan["legacy"])).exists()
    prior_codes = {value for value in (sku.sku_code, sku.legacy_sku_code) if value and value != plan["sku_code"]}
    prior_collision = any(
        ProductSKU.objects.filter(tenant=tenant).exclude(pk=sku.pk).filter(Q(sku_code=code) | Q(legacy_sku_code=code)).exists()
        or ProductSKUAlias.objects.filter(tenant=tenant, code_key=code_key(code)).exclude(sku=sku).exists()
        or ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code=code).exclude(generated_sku=sku).exists()
        for code in prior_codes
    )
    before = {
        "sku_code": sku.sku_code, "spu_id": sku.spu_id, "color_code": sku.color_code,
        "spec_values": sku.spec_values, "legacy_sku_code": sku.legacy_sku_code,
    }
    after = {"sku_code": plan["sku_code"], "spu_id": plan["spu"].pk,
        "spu_code": plan["spu"].spu_code, "color_code": plan["color"],
        "specification": plan["specification"], "spec_values": plan["specs"],
        "legacy_sku_code": plan["legacy"]}
    token = signing.dumps({"tenant_id": tenant.pk, "sku_id": sku.pk, "actor_id": getattr(actor, "pk", None),
        "updated_at": sku.updated_at.isoformat(), "before": before,
        "after": {key: after[key] for key in ("sku_code", "spu_id", "color_code", "spec_values", "legacy_sku_code")}},
        salt="product-sku-identity-preview")
    return {"sku_id": sku.pk, "updated_at": sku.updated_at.isoformat(), "before": before, "after": after,
        "preview_token": token,
        "conflicts": (["目标 SKU 编码已存在"] if collision else []) +
                     (["旧码已被其他商品当前使用或登记为别名"] if alias_collision or current_collision else []) +
                     (["待保留旧码已存在其他商品映射，无法消除歧义"] if prior_collision else [])}


@transaction.atomic
def confirm_controlled_edit(tenant, actor, sku_id, data, allowed_spu_ids=None):
    from apps.tenants.models import Tenant
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    sku = ProductSKU.objects.select_for_update().select_related("spu").get(tenant=tenant, pk=sku_id)
    try:
        token = signing.loads(data.get("preview_token") or "", salt="product-sku-identity-preview", max_age=900)
    except signing.BadSignature as exc:
        raise ValidationError({"preview_token": "预览已失效或内容不匹配，请重新预览。"}) from exc
    if token.get("tenant_id") != tenant.pk or token.get("sku_id") != sku.pk or token.get("actor_id") != getattr(actor, "pk", None):
        raise ValidationError({"preview_token": "预览不属于当前商品或操作人，请重新预览。"})
    expected_at = data.get("updated_at")
    expected = data.get("before") or {}
    if not expected_at or sku.updated_at.isoformat() != expected_at or any(
        expected.get(key) != value for key, value in {
            "sku_code": sku.sku_code, "spu_id": sku.spu_id, "color_code": sku.color_code,
            "spec_values": sku.spec_values, "legacy_sku_code": sku.legacy_sku_code,
        }.items()
    ):
        raise ValidationError({"detail": "商品身份已被其他操作修改，请重新预览。"})
    plan = _plan(tenant, sku, data, allowed_spu_ids)
    token_after = token.get("after") or {}
    expected_after = {"sku_code": plan["sku_code"], "spu_id": plan["spu"].pk, "color_code": plan["color"],
        "spec_values": plan["specs"], "legacy_sku_code": plan["legacy"]}
    if token.get("updated_at") != sku.updated_at.isoformat() or token.get("before") != expected or token_after != expected_after:
        raise ValidationError({"preview_token": "确认内容与预览不一致，请重新预览。"})
    if ProductSKU.objects.filter(tenant=tenant).exclude(pk=sku.pk).filter(Q(sku_code=plan["sku_code"]) | Q(legacy_sku_code=plan["sku_code"])).exists() or ProductSKUAlias.objects.filter(tenant=tenant, code_key=code_key(plan["sku_code"])).exclude(sku=sku).exists():
        raise ValidationError({"sku_code": "目标 SKU 编码已被占用，请重新预览。"})
    if ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code=plan["sku_code"]).exclude(generated_sku=sku).exists():
        raise ValidationError({"sku_code": "目标 SKU 编码已被导入旧码占用，请重新预览。"})
    old_code = sku.sku_code
    # Recheck all alias/current-code collisions under the tenant lock.
    if (ProductSKU.objects.filter(tenant=tenant).exclude(pk=sku.pk).filter(Q(sku_code=plan["legacy"]) | Q(legacy_sku_code=plan["legacy"])).exists()
        or ProductSKUAlias.objects.filter(tenant=tenant, code_key=code_key(plan["legacy"])).exclude(sku=sku).exists()
        or ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code=plan["legacy"]).exclude(generated_sku=sku).exists()):
        raise ValidationError({"legacy_sku_code": "旧 SKU 编码已被其他商品占用，请重新预览。"})
    prior_codes = tuple(dict.fromkeys(value for value in (old_code, sku.legacy_sku_code) if value and value != plan["sku_code"]))
    for prior in prior_codes:
        if (ProductSKU.objects.filter(tenant=tenant).exclude(pk=sku.pk).filter(Q(sku_code=prior) | Q(legacy_sku_code=prior)).exists()
            or ProductSKUAlias.objects.filter(tenant=tenant, code_key=code_key(prior)).exclude(sku=sku).exists()
            or ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code=prior).exclude(generated_sku=sku).exists()):
            raise ValidationError({"sku_code": "待保留旧码已存在其他商品映射，无法消除歧义。"})
    sku.spu = plan["spu"]
    sku.sku_code = plan["sku_code"]
    sku.legacy_sku_code = plan["legacy"]
    sku.color_code = plan["color"]
    sku.specification = plan["specification"]
    sku.spec_values = plan["specs"]
    try:
        sku.save(update_fields=["spu", "sku_code", "legacy_sku_code", "color_code", "specification", "spec_values", "updated_at"])
    except IntegrityError as exc:
        raise ValidationError({"sku_code": "目标 SKU 编码已被占用，请重新预览。"}) from exc
    # Sales-order lines validate that their cached SPU matches the SKU. Keep
    # that derived identity aligned in the same transaction so historical lines
    # remain valid when they are subsequently edited.
    from apps.commerce.models import SalesOrderItem
    SalesOrderItem.objects.filter(sales_order__tenant=tenant, internal_sku_id=sku.pk).exclude(
        internal_spu_id=plan["spu"].pk
    ).update(internal_spu_id=plan["spu"].pk)
    for prior in prior_codes:
        if ProductSKUAlias.objects.filter(sku=sku, code_key=code_key(prior), source="identity_correction").exists():
            continue
        create_alias(sku=sku, actor=actor, source="identity_correction", values={"alias_code": prior,
            "scope_type": "tenant", "effective_from": timezone.now(),
            "effective_to": None, "reason": "受控 SKU 身份修正；跨业务日期按身份别名解析"})
    from apps.audit.services import write_operation_log
    write_operation_log(tenant=tenant, user=actor, module="products", action="product_sku.controlled_identity_edit",
        object_type="ProductSKU", object_id=sku.pk,
        before_data={"sku_code": old_code, "spu_id": expected["spu_id"], "color_code": expected["color_code"], "spec_values": expected["spec_values"], "legacy_sku_code": expected["legacy_sku_code"]},
        after_data={"sku_code": sku.sku_code, "spu_id": sku.spu_id, "color_code": sku.color_code, "spec_values": sku.spec_values, "legacy_sku_code": sku.legacy_sku_code})
    return sku
