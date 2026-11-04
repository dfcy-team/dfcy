"""Read-only CB settlement batches; never post payouts as additional income.

Official contracts: open.shopee.com/documents/v2/v2.payment.get_payout_info
and v2.payment.get_billing_transaction_info (verified 2026-10-21).
Billing rows have no event ID/time: retain repeated equal charges and label the
date as payout time, not an invented adjustment occurrence time.
"""
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


PAYOUT_PATH = "/api/v2/payment/get_payout_info"
BILLING_PATH = "/api/v2/payment/get_billing_transaction_info"
PAYOUT_FIELDS = ("encrypted_payout_id", "from_amount", "from_currency", "payout_amount",
                 "payout_currency", "exchange_rate", "payout_time")
BILLING_FIELDS = ("amount", "currency", "order_sn", "cost_header", "scenario", "remark",
                  "level", "billing_transaction_type", "billing_transaction_status")


def _money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Shopee payout amount is missing or invalid.") from None


def _currency(value):
    if not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ValidationError("Shopee payout currency is missing or invalid.")
    return value.upper()


def _pages(client, path, query, list_key, raw_responses, *, post=False):
    cursor, seen = "", set()
    while True:
        params = {**query, "cursor": cursor}
        payload = client._request(path, {}, readonly_body=params) if post else client._request(path, params)
        data = payload.get("response")
        if not isinstance(data, dict) or not isinstance(data.get(list_key), list):
            raise ValidationError("Shopee payout response is incomplete.")
        more, next_cursor = data.get("more"), data.get("next_cursor")
        if type(more) is not bool or not isinstance(next_cursor, str) or more != bool(next_cursor):
            raise ValidationError("Shopee payout pagination is incomplete.")
        if next_cursor and (next_cursor == cursor or next_cursor in seen):
            raise ValidationError("Shopee payout cursor repeated; collection is incomplete.")
        rows = data[list_key]
        if len(rows) > query["page_size"] or any(not isinstance(row, dict) for row in rows):
            raise ValidationError("Shopee payout page is invalid.")
        # Financial projection deliberately excludes recipient account identifiers.
        fields = BILLING_FIELDS if post else PAYOUT_FIELDS
        projected = [{key: row[key] for key in fields if key in row} for row in rows]
        raw_responses.append({"endpoint": path, "query": params, "financial_projection_only": True,
                              "payload": {"request_id": payload.get("request_id", ""),
                                          "response": {list_key: projected, "more": more, "next_cursor": next_cursor}}})
        yield from projected
        if not more:
            return
        seen.add(next_cursor)
        cursor = next_cursor


def collect_released_payouts(client, scope):
    start, end = scope.get("time_from"), scope.get("time_to")
    page_size = scope.get("page_size", 100)
    if (type(start) is not int or type(end) is not int or start < 0 or start >= end
            or type(page_size) is not int or not 1 <= page_size <= 100):
        raise ValidationError("Shopee payout range or page size is invalid.")
    raw_responses, payouts = [], {}
    for window_start in range(start, end + 1, 15 * 86400):
        window_end = min(end, window_start + 15 * 86400 - 1)
        query = {"payout_time_from": window_start, "payout_time_to": window_end, "page_size": page_size}
        for row in _pages(client, PAYOUT_PATH, query, "payout_list", raw_responses):
            identifier = row.get("encrypted_payout_id")
            if not isinstance(identifier, str) or not identifier:
                raise ValidationError("Shopee payout ID is missing.")
            if type(row.get("payout_time")) is not int or not window_start <= row["payout_time"] <= window_end:
                raise ValidationError("Shopee payout time is outside the requested window.")
            _money(row.get("from_amount"))
            _money(row.get("payout_amount"))
            _currency(row.get("from_currency"))
            _currency(row.get("payout_currency"))
            if identifier in payouts and payouts[identifier] != row:
                raise ValidationError("Shopee returned conflicting versions of a payout.")
            payouts[identifier] = dict(row)

    transactions, summary, unclassified_count = [], {}, 0
    for identifier, payout in payouts.items():
        currency = _currency(payout["from_currency"])
        totals = summary.setdefault(currency, {key: Decimal(0) for key in (
            "order_income", "order_adjustment", "shop_adjustment", "unclassified", "billing_total", "settlement_total")})
        totals["settlement_total"] += _money(payout["from_amount"])
        occurrences = Counter()
        billing_total = Decimal(0)
        query = {"billing_transaction_info_type": 2, "encrypted_payout_ids": [identifier], "page_size": page_size}
        for row in _pages(client, BILLING_PATH, query, "transactions", raw_responses, post=True):
            amount = _money(row.get("amount"))
            if _currency(row.get("currency")) != currency:
                raise ValidationError("Shopee billing currency differs from the payout settlement currency.")
            kind, level = row.get("billing_transaction_type"), row.get("level")
            if row.get("billing_transaction_status") != "RELEASED":
                raise ValidationError("Shopee returned an unreleased billing item in a released payout.")
            bucket = "unclassified"
            if kind == "ESCROW" and level == "ORDER" and row.get("order_sn"):
                bucket = "order_income"
            elif kind == "ADJUSTMENT" and level == "ORDER" and row.get("order_sn"):
                bucket = "order_adjustment"
            elif kind == "ADJUSTMENT" and level == "SHOP" and not row.get("order_sn"):
                bucket = "shop_adjustment"
            unclassified_count += bucket == "unclassified"
            totals[bucket] += amount
            totals["billing_total"] += amount
            billing_total += amount
            canonical = {**row, "amount": str(amount), "currency": currency}
            digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            occurrences[digest] += 1
            transactions.append({**row, "source_key": f"payout:{identifier}:{digest}:{occurrences[digest]}",
                                 "payout_id": identifier, "payout_time": payout["payout_time"],
                                 "date_basis": "payout_time", "reconciliation_bucket": bucket})
        payout["billing_total"] = str(billing_total)
        payout["difference"] = str(billing_total - _money(payout["from_amount"]))
    for totals in summary.values():
        totals["difference"] = totals["billing_total"] - totals["settlement_total"]
    reconciled = bool(payouts) and unclassified_count == 0 and all(_money(row["difference"]) == 0 for row in payouts.values())
    return {"date_basis": "payout_time", "reconciled": reconciled,
            "payouts": list(payouts.values()), "transactions": transactions,
            "summary": {currency: {key: str(value) for key, value in totals.items()} for currency, totals in summary.items()},
            "unclassified_count": unclassified_count, "raw_responses": raw_responses}
