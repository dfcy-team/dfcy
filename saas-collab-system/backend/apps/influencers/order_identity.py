"""Derived business identity; never part of the source fact/revision hash."""
import hashlib
import json

IDENTITY_FIELDS = ("shop_abbr", "site", "order_id", "sku_id")


def order_identity_digest(values):
    normalized = [str(value or "").strip().casefold() for value in values]
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
