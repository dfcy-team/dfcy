"""Validation, preview and transactional allocation for document numbers."""
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .dates import business_date
from .models import DocumentNumberCounter, DocumentNumberRule
from apps.masterdata.models import CountrySiteMaster


KINDS = {key: label for key, label in DocumentNumberRule.KIND_CHOICES}
DEFAULTS = {
    "operating_order": ("OP", "OP-{date}-<12位随机码>"),
    "purchase_order": ("PO", "PO-{date}-<12位随机码>"),
    "supplier_shipment": ("SH", "SH-{date}-<12位随机码>"),
    "dispatch_batch": ("DB", "DB-{date}-<12位随机码>"),
    "inbound_order": ("IN", "IN-<集运批次ID>"),
}
DEFAULT_RULE = {"enabled": False, "include_country": False, "country_prefixes": {}, "date_format": "YYYYMMDD", "separator": "none", "sequence_width": 4, "reset_period": "day"}
DATE_FORMATS = ("YYYYMMDD", "YYMMDD", "YYYYMM", "YYYY", "none")
SEPARATORS = ("-", "_", "none")
RESET_PERIODS = ("day", "month", "year", "never")
RULE_FIELDS = ("enabled", "include_country", "country_prefixes", "prefix", "date_format", "separator", "sequence_width", "reset_period")
DOCUMENT_MODELS = {
    "operating_order": ("apps.sales_management.operating_models", "OperatingOrder"),
    "purchase_order": (".models", "PurchaseOrder"),
    "supplier_shipment": (".models", "SupplierShipment"),
    "dispatch_batch": (".models", "DispatchBatch"),
    "inbound_order": (".models", "InboundOrder"),
}


def validate_rule(data):
    errors = {}
    prefix = data.get("prefix")
    if not isinstance(prefix, str) or not 1 <= len(prefix) <= 12 or not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
        errors["prefix"] = "前缀必须为1至12位大写英文字母或数字，且以字母开头。"
    if data.get("date_format") not in DATE_FORMATS:
        errors["date_format"] = "日期格式无效。"
    if data.get("separator") not in SEPARATORS:
        errors["separator"] = "分隔符无效。"
    width = data.get("sequence_width")
    if isinstance(width, bool) or not isinstance(width, int) or not 3 <= width <= 8:
        errors["sequence_width"] = "流水号位数必须为3至8。"
    period = data.get("reset_period")
    if period not in RESET_PERIODS:
        errors["reset_period"] = "重置周期无效。"
    fmt = data.get("date_format")
    enough = {"day": {"YYYYMMDD", "YYMMDD"}, "month": {"YYYYMMDD", "YYMMDD", "YYYYMM"}, "year": set(DATE_FORMATS) - {"none"}, "never": set(DATE_FORMATS)}
    if period in enough and fmt not in enough[period]:
        errors["date_format"] = "日期格式必须包含重置周期所需的粒度。"
    if errors:
        raise ValidationError(errors)
    mapping = data.get("country_prefixes", {})
    if not isinstance(mapping, dict):
        raise ValidationError({"country_prefixes": "国家前缀必须为国家代码到前缀的映射。"})
    country_codes = set(CountrySiteMaster.objects.filter(tenant_id=data.get("tenant_id")).values_list("country_code", flat=True).distinct())
    for code, value in mapping.items():
        if not isinstance(code, str) or not code or code != code.upper() or code not in country_codes:
            raise ValidationError({"country_prefixes": f"国家代码 {code!r} 不属于当前租户。"})
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9]{0,7}", value):
            raise ValidationError({"country_prefixes": f"国家 {code} 的前缀必须为1至8位大写英文字母或数字，且以字母开头。"})
    if data.get("include_country"):
        seen = {}
        for code in country_codes:
            value = mapping.get(code, code)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9]{0,7}", value):
                raise ValidationError({"include_country": f"国家代码 {code} 不能用作有效前缀，请设置符合格式的自定义前缀。"})
            if value in seen:
                raise ValidationError({"country_prefixes": f"国家前缀 {value} 同时用于 {seen[value]} 和 {code}，请保证每个国家的有效前缀唯一。"})
            seen[value] = code
    result = {field: data[field] for field in RULE_FIELDS}
    result["country_prefixes"] = dict(mapping)
    return result


def period_key(reset_period, day):
    if reset_period == "day":
        return f"day:{day:%Y%m%d}"
    if reset_period == "month":
        return f"month:{day:%Y%m}"
    if reset_period == "year":
        return f"year:{day:%Y}"
    return "never"


def _date_component(fmt, day):
    return {"YYYYMMDD": day.strftime("%Y%m%d"), "YYMMDD": day.strftime("%y%m%d"),
            "YYYYMM": day.strftime("%Y%m"), "YYYY": day.strftime("%Y"), "none": ""}[fmt]


def format_number(rule, sequence, day, country_code=""):
    parts = []
    if rule.get("include_country"):
        country_prefix = rule.get("country_prefixes", {}).get(country_code, country_code)
        parts.append(country_prefix)
    parts.extend([rule["prefix"], _date_component(rule["date_format"], day), str(sequence).zfill(rule["sequence_width"])])
    parts = [part for part in parts if part]
    separator = "" if rule["separator"] == "none" else rule["separator"]
    return separator.join(parts)


def _rule_values(rule):
    if isinstance(rule, DocumentNumberRule):
        return {field: getattr(rule, field) for field in RULE_FIELDS}
    return {**DEFAULT_RULE, **rule}


def _exists(tenant_id, kind, candidate):
    model = DOCUMENT_MODELS[kind]
    if model[0].startswith("."):
        from . import models as module
    else:
        from apps.sales_management import operating_models as module
    return getattr(module, model[1]).objects.filter(tenant_id=tenant_id, number=candidate).exists()


def preview(kind, rule_data, tenant_id, *, day=None, country_code=""):
    if kind not in KINDS:
        raise ValidationError("未知单据类型。")
    values = validate_rule({**rule_data, "tenant_id": tenant_id})
    day = day or business_date()
    if values["include_country"]:
        if not country_code or not CountrySiteMaster.objects.filter(tenant_id=tenant_id, country_code=country_code).exists():
            raise ValidationError({"country_code": "请选择当前租户内的有效国家。"})
    else:
        country_code = ""
    key = period_key(values["reset_period"], day)
    if not values["enabled"]:
        legacy = DEFAULTS[kind][1]
        return {"example": legacy.format(date=day.strftime("%Y%m%d")), "sequence": None,
                "period_key": key, "business_date": day.isoformat(), "enabled": False}
    counter = DocumentNumberCounter.objects.filter(tenant_id=tenant_id, kind=kind, country_code=country_code, period_key=key).first()
    seq = (counter.value if counter else 0) + 1
    capacity = 10 ** values["sequence_width"] - 1
    for _ in range(1000):
        if seq > capacity:
            raise ValidationError("当前周期流水号位数已用尽，请增加位数或调整重置周期。")
        candidate = format_number(values, seq, day, country_code)
        if not _exists(tenant_id, kind, candidate):
            return {"example": candidate, "sequence": seq, "period_key": key,
                    "business_date": day.isoformat(), "enabled": True}
        seq += 1
    raise ValidationError("连续1000个候选编号均已存在，请调整编号规则。")


def number_for(actor, kind, legacy, country_code=""):
    """Allocate a number when configured; otherwise return the existing legacy number."""
    rule = DocumentNumberRule.objects.filter(tenant_id=actor.tenant_id, kind=kind).first()
    if not rule or not rule.enabled:
        return legacy
    if rule.include_country:
        if not country_code:
            raise ValidationError("该编号规则要求提供国家代码。")
    else:
        country_code = ""
    day = business_date()
    key = period_key(rule.reset_period, day)
    try:
        counter = DocumentNumberCounter.objects.select_for_update().filter(
            tenant_id=actor.tenant_id, kind=kind, country_code=country_code, period_key=key).first()
        if counter is None:
            try:
                with transaction.atomic():
                    counter = DocumentNumberCounter.objects.create(tenant=actor.tenant, created_by=actor,
                        kind=kind, country_code=country_code, period_key=key, value=0)
            except IntegrityError:
                counter = DocumentNumberCounter.objects.select_for_update().get(
                    tenant_id=actor.tenant_id, kind=kind, country_code=country_code, period_key=key)
        capacity = 10 ** rule.sequence_width - 1
        seq = counter.value + 1
        for _ in range(1000):
            if seq > capacity:
                raise ValidationError("当前周期流水号位数已用尽，请增加位数或调整重置周期。")
            candidate = format_number(_rule_values(rule), seq, day, country_code)
            if not _exists(actor.tenant_id, kind, candidate):
                counter.value = seq
                counter.save(update_fields=["value", "updated_at"])
                return candidate
            seq += 1
        raise ValidationError("连续1000个候选编号均已存在，请调整编号规则。")
    except ValidationError:
        raise
