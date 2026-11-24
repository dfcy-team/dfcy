"""Build values for the native Feishu payment approval form."""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import json
import math

from rest_framework.exceptions import ValidationError


def _select(widget, requested, label):
    options = widget.get("option")
    if not isinstance(options, list) or not options:
        raise ValidationError(f"{label}控件选项缺失或格式不支持。")
    matches = [item for item in options if isinstance(item, dict) and requested in (item.get("value"), item.get("text"))]
    if len(matches) != 1 or not matches[0].get("value"):
        raise ValidationError(f"{label}必须提供可唯一匹配的选项标签或value。")
    return matches[0]["value"]


def _date_value(value):
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime.combine(value, time.min)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("付款申请计划日期无效。")
    if dt.tzinfo is None:
        return dt.isoformat(timespec="seconds") + "+08:00"
    return dt.isoformat(timespec="seconds")


def build_payment_form(definition, *, reason, amount, currency, account_snapshot, payment_type, payment_method, payment_date):
    """Return Feishu approval v4 instance form widget values."""
    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("付款金额必须是正有限数字。")
    if not decimal_amount.is_finite() or decimal_amount <= 0:
        raise ValidationError("付款金额必须是正有限数字。")
    # Feishu's native amount widget accepts a JSON number (float) and currency.
    api_amount = float(decimal_amount)
    if not math.isfinite(api_amount) or Decimal(str(api_amount)) != decimal_amount:
        raise ValidationError("付款金额超出接口可表示范围。")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("付款事由不能为空。")
    if not isinstance(account_snapshot, dict):
        raise ValidationError("收款账户快照格式无效。")

    form = definition.get("form") if isinstance(definition, dict) else None
    if isinstance(form, str):
        try:
            form = json.loads(form)
        except (TypeError, ValueError):
            form = None
    if not isinstance(form, list):
        raise ValidationError("审批定义表单缺失或格式无效。")
    supported = {"付款事由", "付款类型", "付款金额", "付款方式", "付款日期", "收款人", "开户银行", "收款账号"}
    values = {
        "付款事由": reason.strip(),
        "付款类型": payment_type,
        "付款方式": payment_method,
        "付款日期": _date_value(payment_date),
        "收款人": account_snapshot.get("account_holder"),
        "开户银行": account_snapshot.get("bank_name"),
        "收款账号": account_snapshot.get("account_number"),
    }
    currency = str(currency).upper() if currency is not None else ""
    result = []
    seen = set()
    for widget in form:
        if not isinstance(widget, dict):
            raise ValidationError("审批定义包含无法识别的控件。")
        if not widget.get("required"):
            continue
        name = widget.get("name")
        if name not in supported:
            raise ValidationError(f"存在不支持的必填控件：{name or '未命名'}。")
        if name in seen:
            raise ValidationError(f"必填控件名称重复，无法确定映射：{name}。")
        seen.add(name)
        kind = widget.get("type")
        entry = {"id": widget.get("id"), "type": kind}
        if not entry["id"]:
            raise ValidationError(f"必填控件缺少id：{name}。")
        if name in ("付款类型", "付款方式"):
            if kind not in ("radio", "radioV2"):
                raise ValidationError(f"{name}控件类型不支持。")
            entry["value"] = _select(widget, values[name], name)
        elif name == "付款金额":
            if kind != "amount":
                raise ValidationError("付款金额控件类型不支持。")
            supported_currencies = (widget.get("option") or {}).get("currencyRange")
            if not isinstance(supported_currencies, list) or currency not in supported_currencies:
                raise ValidationError("付款币种不在模板支持范围内。")
            entry.update(value=api_amount, currency=currency)
        elif name == "付款日期":
            if kind != "date":
                raise ValidationError("付款日期控件类型不支持。")
            entry["value"] = values[name]
        elif name == "付款事由":
            if kind != "textarea":
                raise ValidationError("付款事由控件类型不支持。")
            entry["value"] = values[name]
        else:
            if kind != "input":
                raise ValidationError(f"{name}控件类型不支持。")
            value = values[name]
            if value is None or str(value).strip() == "":
                raise ValidationError(f"收款账户快照缺少{name}。")
            entry["value"] = str(value)  # Preserve leading zeros in account numbers.
        result.append(entry)
    if seen != supported:
        missing = sorted(supported - seen)
        raise ValidationError(f"付款模板缺少必填控件：{', '.join(missing)}。")
    return result
