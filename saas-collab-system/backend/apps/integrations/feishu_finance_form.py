"""Pure, fail-closed parsing helpers for Feishu finance completion forms."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import csv
import io
from datetime import date, datetime
from pathlib import PurePath
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit


MAX_FILE_BYTES = 20 * 1024 * 1024


class FinanceFormError(ValueError):
    """Invalid or ambiguous finance form data; callers must not complete finance."""


def _form_list(authoritative):
    if isinstance(authoritative, str):
        try:
            authoritative = json.loads(authoritative)
        except (TypeError, ValueError) as exc:
            raise FinanceFormError("authoritative form is not valid JSON") from exc
    if not isinstance(authoritative, list) or not all(isinstance(x, dict) for x in authoritative):
        raise FinanceFormError("authoritative form must be a list of widget objects")
    return authoritative


def _date_value(value):
    if not isinstance(value, str) or not value.strip():
        raise FinanceFormError("actual payment date is missing or invalid")
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            result = date.fromisoformat(value)
        else:
            # RFC3339 must carry a timezone; UTC is converted to the business date.
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
            result = parsed.astimezone(ZoneInfo("Asia/Shanghai")).date()
    except (ValueError, OverflowError) as exc:
        raise FinanceFormError("actual payment date must be YYYY-MM-DD or RFC3339") from exc
    if result > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise FinanceFormError("actual payment date cannot be in the future")
    return result


def parse_finance_form(authoritative, *, date_widget_id, voucher_widget_id):
    """Parse only configured widget IDs; reject duplicates and unknown attachment shapes."""
    if not date_widget_id or not voucher_widget_id or date_widget_id == voucher_widget_id:
        raise FinanceFormError("finance widget IDs must be distinct and configured")
    widgets = _form_list(authoritative)
    found = {}
    for widget in widgets:
        wid = widget.get("id", widget.get("widget_id"))
        if wid in (date_widget_id, voucher_widget_id):
            if wid in found:
                raise FinanceFormError("duplicate finance widget ID")
            found[wid] = widget
    if date_widget_id not in found or voucher_widget_id not in found:
        raise FinanceFormError("configured finance widget missing")
    date_widget, file_widget = found[date_widget_id], found[voucher_widget_id]
    if date_widget.get("type") != "date":
        raise FinanceFormError("configured date widget is not a date control")
    if file_widget.get("type") not in {"attachment", "attachmentV2", "image", "imageV2"}:
        raise FinanceFormError("configured voucher widget is not an attachment or image control")
    paid_date = _date_value(date_widget.get("value"))
    raw_files = file_widget.get("value")
    if not raw_files:
        raise FinanceFormError("voucher attachment is empty or has unsupported shape")
    if isinstance(raw_files, list) and all(isinstance(item, str) for item in raw_files):
        names = _ext_names(file_widget.get("ext"))
        if len(names) != len(raw_files):
            raise FinanceFormError("attachment URL and ext filename counts differ")
        entries = [{"url": url, "name": name} for url, name in zip(raw_files, names)]
    elif isinstance(raw_files, list) and all(isinstance(item, dict) for item in raw_files):
        entries = raw_files
    else:
        raise FinanceFormError("voucher attachment has unsupported shape")
    files = []
    seen_keys = set()
    for item in entries:
        url = item.get("url")
        name = item.get("name")
        if not name and isinstance(file_widget.get("ext"), str):
            names = _ext_names(file_widget["ext"])
            if len(names) != len(entries):
                raise FinanceFormError("attachment URL and ext filename counts differ")
            name = names[len(files)]
        source_key = item.get("source_key", item.get("file_token"))
        canonical = _canonical_url(url)
        if not isinstance(name, str) or not name.strip():
            raise FinanceFormError("voucher attachment filename is missing")
        name = _safe_filename(name)
        if not source_key:
            source_key = "urlsha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if not isinstance(source_key, str) or not source_key.strip():
            raise FinanceFormError("voucher attachment source key is invalid")
        if source_key in seen_keys:
            raise FinanceFormError("duplicate voucher attachment source key")
        seen_keys.add(source_key)
        files.append({"url": url, "name": name, "source_key": source_key})
    return {"actual_payment_date": paid_date, "files": files}


def _ext_names(value):
    if not isinstance(value, str) or not value.strip():
        raise FinanceFormError("attachment ext filenames are missing")
    try:
        rows = list(csv.reader(io.StringIO(value), strict=True, skipinitialspace=True, quotechar="'"))
    except (csv.Error, TypeError) as exc:
        raise FinanceFormError("attachment ext filenames are invalid CSV") from exc
    if len(rows) != 1 or not rows[0] or any(not item.strip() for item in rows[0]):
        raise FinanceFormError("attachment ext filenames are ambiguous")
    return [_safe_filename(item.strip()) for item in rows[0]]


def _canonical_url(url):
    if not isinstance(url, str) or not url.strip():
        raise FinanceFormError("voucher attachment URL is missing")
    try:
        parts = urlsplit(url.strip())
        if (parts.scheme.lower() != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)):
            raise ValueError("unsafe URL")
        host = parts.hostname.lower()
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit(("https", host + port, parts.path, "", ""))
    except (ValueError, TypeError) as exc:
        raise FinanceFormError("voucher attachment URL must be a valid HTTPS URL") from exc


def _safe_filename(name):
    if not isinstance(name, str) or not name.strip():
        raise FinanceFormError("declared filename is required")
    leaf = name.replace("\\", "/").split("/")[-1]
    leaf = "".join(ch for ch in leaf if unicodedata.category(ch)[0] != "C").strip(" .")
    suffix = PurePath(leaf).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise FinanceFormError("filename must have a PDF, PNG, or JPEG extension")
    stem = PurePath(leaf).stem.strip(" .") or "voucher"
    return f"{stem}{suffix}"


def validate_finance_file(content, *, declared_name, content_type):
    """Validate already-downloaded bytes. This function never fetches or logs a URL."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise FinanceFormError("file content must be bytes")
    content = bytes(content)
    if not content or len(content) > MAX_FILE_BYTES:
        raise FinanceFormError("file is empty or exceeds 20 MiB")
    filename = _safe_filename(declared_name)
    signatures = (
        (b"%PDF-", ".pdf", "application/pdf"),
        (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
        (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    )
    match = next((entry for entry in signatures if content.startswith(entry[0])), None)
    if match is None:
        raise FinanceFormError("file signature is not PDF, PNG, or JPEG")
    _, extension, media_type = match
    if extension == ".jpg" and filename.endswith(".jpeg"):
        pass
    elif PurePath(filename).suffix != extension:
        raise FinanceFormError("filename extension does not match file signature")
    declared_type = content_type.split(";", 1)[0].strip().lower() if isinstance(content_type, str) else ""
    if declared_type == "application/octet-stream":
        pass
    elif declared_type != media_type:
        raise FinanceFormError("declared content type does not match file signature")
    return {"filename": filename, "media_type": media_type, "byte_size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
