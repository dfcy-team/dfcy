"""Controlled SPU/SKU code reassignment helpers."""
import re

from django.db import transaction
from django.db.models import Q

from .models import ProductSPU, ProductSKU

CODE_RE = re.compile(r"^[0-9A-Z]$")
SEQ_RE = re.compile(r"^[0-9]{3}$")


def _conflict(code, message, field):
    return {"code": code, "message": message, "field": field}


def plan_recode(tenant, rows):
    result = []
    seen_spus, seen_skus = {}, {}
    for number, row in enumerate(rows, 1):
        row_number = row.get("row_number") or number
        source = str(row.get("source_spu_code") or row.get("spu_code") or "").strip()
        attr = str(row.get("attribute_code") or "").strip().upper()
        seq = str(row.get("serial_number") or "").strip()
        product_name = row.get("product_name")
        product_name = str(product_name).strip() if product_name is not None else None
        conflicts = []
        matches = list(ProductSPU.objects.filter(tenant=tenant).filter(Q(spu_code=source) | Q(legacy_spu_code=source))) if source else []
        if not source:
            conflicts.append(_conflict("source_required", "缺少原SPU编码", "source_spu_code"))
        elif len(matches) != 1:
            conflicts.append(_conflict("source_not_unique", "原SPU编码不存在或匹配到多条记录", "source_spu_code"))
        spu = matches[0] if len(matches) == 1 else None
        if spu and (spu.is_code_frozen or spu.lifecycle_status != ProductSPU.LifecycleStatus.DRAFT or spu.sales_status != ProductSPU.SalesStatus.NOT_LISTED):
            conflicts.append(_conflict("state_not_allowed", "SPU必须为未冻结、草稿且未刊登状态", "status"))
        if spu and spu.skus.filter(is_code_frozen=True).exists():
            conflicts.append(_conflict("sku_frozen", "旗下SKU存在已冻结编码", "status"))
        if not CODE_RE.fullmatch(attr):
            conflicts.append(_conflict("invalid_attribute", "属性编码必须为一位数字或大写字母", "attribute_code"))
        if not SEQ_RE.fullmatch(seq) or int(seq) > 999:
            conflicts.append(_conflict("invalid_sequence", "流水必须为000-999三位数字", "sequence"))
        target = (spu.spu_code[:-4] + attr + seq) if spu and len(spu.spu_code) >= 4 and CODE_RE.fullmatch(attr) and SEQ_RE.fullmatch(seq) else ""
        if spu and len(spu.spu_code) < 4:
            conflicts.append(_conflict("invalid_source_format", "原SPU编码不符合属性码+三位流水结构", "source_spu_code"))
        if target and target == spu.spu_code:
            conflicts.append(_conflict("code_unchanged", "目标SPU编码与当前编码相同", "target_spu_code"))
        if target and target != spu.spu_code:
            if ProductSPU.objects.filter(tenant=tenant, spu_code=target).exclude(pk=spu.pk).exists():
                conflicts.append(_conflict("spu_target_exists", "目标SPU编码已存在", "target_spu_code"))
            if target in seen_spus:
                conflicts.append(_conflict("duplicate_target", "本批次目标SPU编码重复", "target_spu_code"))
            seen_spus[target] = row_number
        sku_plans = []
        if spu and target:
            for sku in spu.skus.all():
                if not sku.sku_code.startswith(spu.spu_code):
                    conflicts.append(_conflict("sku_prefix_mismatch", f"SKU {sku.sku_code} 不以当前SPU编码开头", "sku_code"))
                    continue
                suffix = sku.sku_code[len(spu.spu_code):]
                new_code = target + suffix
                sku_conflicts = []
                if ProductSKU.objects.filter(tenant=tenant, sku_code=new_code).exclude(pk=sku.pk).exists():
                    sku_conflicts.append(_conflict("sku_target_exists", "目标SKU编码已存在", "target_sku_code"))
                if new_code in seen_skus:
                    sku_conflicts.append(_conflict("duplicate_sku_target", "本批次目标SKU编码重复", "target_sku_code"))
                seen_skus[new_code] = row_number
                sku_plans.append({"id": sku.pk, "source": sku.sku_code, "target": new_code, "conflicts": sku_conflicts})
                conflicts.extend(sku_conflicts)
        result.append({"row_number": row_number, "source": source, "target": target, "attribute_code": attr, "product_name": product_name, "status": "conflict" if conflicts else "ready", "conflicts": conflicts, "spu": spu, "skus": sku_plans})
    return result


def execute_recode(tenant, plans):
    with transaction.atomic():
        locked = []
        for plan in plans:
            spu = ProductSPU.objects.select_for_update().get(tenant=tenant, pk=plan["spu"].pk)
            skus = list(ProductSKU.objects.select_for_update().filter(tenant=tenant, spu=spu))
            old_spu = spu.spu_code
            if not spu.legacy_spu_code:
                spu.legacy_spu_code = old_spu
            spu.spu_code = plan["target"]
            spu.season_code = plan["attribute_code"]
            if plan["product_name"] is not None:
                spu.product_name = plan["product_name"]
            spu.save(update_fields=["spu_code", "legacy_spu_code", "season_code", "product_name", "updated_at"])
            for sku in skus:
                old = sku.sku_code
                if not sku.legacy_sku_code:
                    sku.legacy_sku_code = old
                suffix = old[len(old_spu):] if old.startswith(old_spu) else ""
                sku.sku_code = plan["target"] + suffix
                sku.save(update_fields=["sku_code", "legacy_sku_code", "updated_at"])
            locked.append(spu)
        return locked
