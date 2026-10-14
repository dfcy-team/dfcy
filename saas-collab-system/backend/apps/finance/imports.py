"""Bounded CSV imports of user-provided settlement facts, never payments."""
import csv
import hashlib
import io
import re
from decimal import Decimal

from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.permissions.ui_p6_scopes import finance_values_allowed
from .models import BankReceiptImport, FinanceAuditLog, PlatformStatement, WithdrawalRecord

MAX_BYTES = 1024 * 1024
MAX_ROWS = 500


class FactRow(serializers.Serializer):
    currency = serializers.RegexField(r"^[A-Za-z]{3}$")

    def validate_currency(self, value):
        return value.upper()


def money():
    return serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class StatementRow(FactRow):
    platform = serializers.ChoiceField(choices=["shopee", "lazada", "tiktok"])
    statement_no = serializers.CharField(max_length=80)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    gross_amount = money()
    fee_amount = money()
    net_amount = money()

    def validate(self, attrs):
        if attrs["period_end"] < attrs["period_start"]:
            raise ValidationError({"period_end": "结束日期不能早于开始日期。"})
        if attrs["gross_amount"] - attrs["fee_amount"] != attrs["net_amount"]:
            raise ValidationError({"net_amount": "净额必须等于总额减费用。"})
        return attrs


class WithdrawalRow(FactRow):
    platform = serializers.ChoiceField(choices=["shopee", "lazada", "tiktok"])
    withdrawal_no = serializers.CharField(max_length=80)
    requested_amount = money()
    expected_amount = money()
    requested_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField()

    def validate(self, attrs):
        for name in ("requested_at", "completed_at"):
            if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", str(self.initial_data.get(name, ""))):
                raise ValidationError({name: "时间必须包含时区，例如 2026-10-01T08:00:00+08:00。"})
        if attrs["completed_at"] < attrs["requested_at"]:
            raise ValidationError({"completed_at": "完成时间不能早于申请时间。"})
        if attrs["expected_amount"] > attrs["requested_amount"]:
            raise ValidationError({"expected_amount": "预计到账不能超过申请金额。"})
        if attrs["expected_amount"] <= 0:
            raise ValidationError({"expected_amount": "已完成提现的预计到账金额必须大于零。"})
        return attrs


class ReceiptRow(FactRow):
    reference_no = serializers.CharField(max_length=120)
    import_batch_no = serializers.CharField(max_length=80)
    masked_account = serializers.RegexField(r"^\*{4,}\d{0,4}$", max_length=80)
    receipt_amount = money()
    receipt_date = serializers.DateField()

    def validate_receipt_amount(self, value):
        if value <= 0:
            raise ValidationError("到账金额必须大于零。")
        return value


FORMATS = {
    "statements": (StatementRow, PlatformStatement, "statement_no"),
    "withdrawals": (WithdrawalRow, WithdrawalRecord, "withdrawal_no"),
    "bank-receipts": (ReceiptRow, BankReceiptImport, "reference_no"),
}


def templates():
    return {kind: list(serializer().fields) for kind, (serializer, _, _) in FORMATS.items()}


def parse_upload(user, kind, uploaded):
    if kind not in FORMATS:
        raise ValidationError({"kind": "请选择账单、提现或银行到账。"})
    if uploaded is None:
        raise ValidationError({"file": "请选择 UTF-8 CSV 文件。"})
    raw = uploaded.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValidationError({"file": "文件不能超过 1 MB。"})
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError({"file": "请使用 UTF-8 编码。"})
    if "\x00" in text:
        raise ValidationError({"file": "文件含有无效字符。"})
    schema, model, key = FORMATS[kind]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = set(schema().fields)
    try:
        headers = reader.fieldnames
    except csv.Error:
        raise ValidationError({"file": "CSV 表头格式无效。"})
    if not headers or len(headers) != len(fields) or set(headers) != fields:
        raise ValidationError({"file": "CSV 表头必须与下载的模板完全一致。"})
    rows, errors, seen = [], [], set()
    try:
        for line, data in enumerate(reader, start=2):
            if line > MAX_ROWS + 1:
                raise ValidationError({"file": "一次最多导入 500 条，请拆分文件。"})
            if None in data or any(v is None for v in data.values()):
                errors.append({"row": line, "fields": {"row": ["列数与表头不一致。"]}})
                continue
            item = schema(data=data)
            if not item.is_valid():
                errors.append({"row": line, "fields": item.errors})
                continue
            values = dict(item.validated_data)
            # Receipts have no source platform. Platform-limited grants cannot
            # authorize an unassigned receipt through an inferred platform.
            if not finance_values_allowed(user, "finance.import", platform=values.get("platform", ""), currency=values["currency"]):
                raise PermissionDenied("文件包含超出当前财务导入数据范围的记录。")
            if values[key] in seen:
                errors.append({"row": line, "fields": {key: ["文件内编号重复。"]}})
            elif values[key].upper().startswith("DEMO-"):
                errors.append({"row": line, "fields": {key: ["不能使用演示数据编号。"]}})
            else:
                seen.add(values[key])
                if kind == "statements":
                    values.update(source_type=PlatformStatement.SourceType.MANUAL_IMPORT)
                if kind == "withdrawals":
                    values.update(status=WithdrawalRecord.Status.COMPLETED)
                rows.append(values)
    except csv.Error:
        raise ValidationError({"file": "CSV 格式无效。"})
    if errors:
        raise ValidationError({"rows": errors[:20], "error_count": len(errors)})
    if not rows:
        raise ValidationError({"file": "文件没有有效数据行。"})
    # Check all identities before any mutation, including preview. Existing
    # financial facts are immutable here; conflicts need explicit correction.
    existing = {getattr(obj, key): obj for obj in model.objects.filter(tenant=user.tenant, **{key + "__in": [r[key] for r in rows]})}
    duplicates = 0
    for row in rows:
        obj = existing.get(row[key])
        if obj:
            if any(getattr(obj, name) != value for name, value in row.items()):
                raise ValidationError({"file": "已有相同编号且内容不同的记录；请先核实，不会覆盖已有财务数据。"})
            duplicates += 1
    summary = {"kind": kind, "rows": len(rows), "new_rows": len(rows) - duplicates, "duplicate_rows": duplicates, "sha256": hashlib.sha256(raw).hexdigest(), "preview": [{"reference": r[key], "platform": r.get("platform", ""), "currency": r["currency"], "amount": str(r.get("net_amount", r.get("expected_amount", r.get("receipt_amount"))))} for r in rows[:20]]}
    return rows, summary


def commit_upload(user, kind, uploaded, expected_hash):
    rows, summary = parse_upload(user, kind, uploaded)
    if expected_hash != summary["sha256"]:
        raise ValidationError({"sha256": "文件与预检结果不一致，请重新预检。"})
    _, model, key = FORMATS[kind]
    created = 0
    try:
        with transaction.atomic():
            for values in rows:
                obj, new = model.objects.get_or_create(tenant=user.tenant, **{key: values[key]}, defaults=values)
                if not new and any(getattr(obj, name) != value for name, value in values.items()):
                    raise ValidationError({"file": "导入期间发现编号冲突，整个批次已取消。"})
                created += int(new)
            FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, action="import_finance_csv", object_type="FinanceImportBatch", object_id=summary["sha256"], masked_detail={"kind": kind, "rows": len(rows), "created": created, "skipped": len(rows) - created})
    except IntegrityError:
        raise ValidationError({"file": "导入编号发生并发冲突，整个批次已取消，请重新预检。"})
    return {"kind": kind, "rows": len(rows), "created": created, "skipped": len(rows) - created, "sha256": summary["sha256"]}
