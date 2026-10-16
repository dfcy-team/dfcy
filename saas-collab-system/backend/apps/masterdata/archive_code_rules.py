import re

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import ArchiveCodeRule, SupplierMaster


DEFAULTS = {
    ArchiveCodeRule.Kind.SUPPLIER: "GY",
    ArchiveCodeRule.Kind.FREIGHT: "HY",
}


def rule_data(rule, kind):
    prefix = rule.prefix if rule else DEFAULTS[kind]
    separator = rule.separator if rule else ""
    width = rule.sequence_width if rule else 3
    sequence = rule.next_sequence if rule else 1
    return {
        "kind": kind,
        "is_enabled": rule.is_enabled if rule else False,
        "prefix": prefix,
        "separator": separator,
        "sequence_width": width,
        "next_sequence": sequence,
        "preview": f"{prefix}{separator}{sequence:0{width}d}",
    }


def all_rule_data(tenant):
    rules = {rule.kind: rule for rule in ArchiveCodeRule.objects.filter(tenant=tenant)}
    return [rule_data(rules.get(kind), kind) for kind in DEFAULTS]


def validate_rule_data(data):
    if not isinstance(data, dict) or data.get("kind") not in DEFAULTS:
        raise ValidationError({"kind": "请选择供应商档案或货运公司。"})
    kind = data["kind"]
    prefix = str(data.get("prefix", "")).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,15}", prefix):
        raise ValidationError({"prefix": "前缀须以英文字母开头，只能包含大写字母和数字，最多 16 位。"})
    separator = data.get("separator", "")
    if separator not in ("", "-"):
        raise ValidationError({"separator": "分隔符只能为空或连字符。"})
    width = data.get("sequence_width")
    if type(width) is not int or not 2 <= width <= 8:
        raise ValidationError({"sequence_width": "流水号位数须为 2 至 8 的整数。"})
    if type(data.get("is_enabled")) is not bool:
        raise ValidationError({"is_enabled": "请选择是否启用自动生成。"})
    return {"kind": kind, "prefix": prefix, "separator": separator,
            "sequence_width": width, "is_enabled": data["is_enabled"]}


@transaction.atomic
def save_rule_data(tenant, rows):
    if not isinstance(rows, list) or len(rows) != len(DEFAULTS):
        raise ValidationError({"rules": "请同时提交供应商和货运公司的编码规则。"})
    validated = [validate_rule_data(row) for row in rows]
    if {row["kind"] for row in validated} != set(DEFAULTS):
        raise ValidationError({"rules": "每类档案须且只能配置一条规则。"})
    for data in validated:
        kind = data.pop("kind")
        rule, _ = ArchiveCodeRule.objects.select_for_update().get_or_create(
            tenant=tenant, kind=kind, defaults={**data, "next_sequence": 1}
        )
        for field, value in data.items():
            setattr(rule, field, value)
        rule.save()
    return all_rule_data(tenant)


@transaction.atomic
def allocate_archive_code(tenant, kind):
    rule = ArchiveCodeRule.objects.select_for_update().filter(tenant=tenant, kind=kind).first()
    if rule is None or not rule.is_enabled:
        raise ValidationError({"code": "请填写档案编码，或先在基础档案设置中启用该类档案的自动编码规则。"})
    if kind == ArchiveCodeRule.Kind.SUPPLIER:
        archive_model = SupplierMaster
    elif kind == ArchiveCodeRule.Kind.FREIGHT:
        from apps.supply_chain.models import FreightCompany
        archive_model = FreightCompany
    else:
        raise ValidationError({"kind": "未知的档案编码类型。"})
    sequence = rule.next_sequence
    while True:
        code = f"{rule.prefix}{rule.separator}{sequence:0{rule.sequence_width}d}"
        if len(code) > 80:
            raise ValidationError({"code": "自动编码已超出档案编码长度，请调整规则。"})
        if not archive_model.objects.filter(tenant=tenant, code=code).exists():
            break
        sequence += 1
    rule.next_sequence = sequence + 1
    rule.save(update_fields=["next_sequence", "updated_at"])
    return code
