import hashlib
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import LazadaFinanceWide, PlatformFinanceTransaction


MONEY_QUANT = Decimal("0.0001")
FEE_COLUMNS = {
    "item price credit": "item_price_credit",
    "reversal item price": "reversal_item_price",
    "commission": "commission",
    "payment fee": "payment_fee",
    "payment fee credit": "payment_fee_credit",
    "reversal commission": "reversal_commission",
    "free shipping max fee": "free_shipping_max_fee",
    "reversal of free shipping max fee": "reversal_free_shipping_max_fee",
    "shipping fee refund to customer": "shipping_fee_refund_to_customer",
    "shipping fee voucher refund to laz": "shipping_fee_voucher_refund_to_laz",
    "sponsored affiliates": "sponsored_affiliates",
    "promotional charges vouchers": "promotional_charges_vouchers",
    "reversal promotional charges vouchers": "reversal_promotional_charges_vouchers",
    "promotional charges flexi-combo": "promotional_charges_flexi_combo",
    "reversal promotional charges flexi-combo": "reversal_promotional_charges_flexi_combo",
    "lazcoins discount": "lazcoins_discount",
    "reversal of lazcoins discount": "reversal_lazcoins_discount",
    "lazcoins discount promotion fee": "lazcoins_discount_promotion_fee",
    "reversal of lazcoins discount promotion fee": "reversal_lazcoins_discount_promotion_fee",
    "order processing fee": "order_processing_fee",
    "reversal order processing fee": "reversal_order_processing_fee",
    "spa program fee": "spa_program_fee",
    "reversal of spa program fee": "reversal_spa_program_fee",
    "wrong shipping fee adjustment": "wrong_shipping_fee_adjustment",
    "withholding tax (lzd - adj debit)": "withholding_tax",
}
AMOUNT_FIELDS = tuple(dict.fromkeys((*FEE_COLUMNS.values(), "other_fee")))


def _money(value):
    return Decimal(value or 0).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _item_key(row):
    if row.external_order_item_id:
        return row.external_order_item_id
    if row.sales_order_item_id:
        return row.sales_order_item.external_line_id
    return ""


def _grain(row, item_key):
    return (
        row.business_date,
        row.currency,
        row.external_order_id,
        item_key,
    )


def _split_amount(amount, targets, weights):
    if not targets:
        return []
    total_weight = sum(weights, Decimal("0"))
    if total_weight <= 0:
        weights = [Decimal("1") for _target in targets]
        total_weight = Decimal(len(targets))
    allocations = []
    allocated = Decimal("0")
    for index, weight in enumerate(weights):
        value = amount - allocated if index == len(targets) - 1 else _money(amount * weight / total_weight)
        allocations.append(value)
        allocated += value
    return allocations


def _hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_lazada_finance_wide_rows(rows):
    rows = list(rows)
    direct_grains = defaultdict(list)
    sales_weights = defaultdict(Decimal)
    for row in rows:
        item_key = _item_key(row)
        if not item_key:
            continue
        grain = _grain(row, item_key)
        direct_grains[grain].append(row)
        if FEE_COLUMNS.get((row.raw_fee_name or "").strip().lower()) == "item_price_credit":
            sales_weights[grain] += abs(_money(row.signed_amount))

    expanded = []
    for row in rows:
        item_key = _item_key(row)
        if item_key:
            expanded.append((row, _grain(row, item_key), _money(row.signed_amount), "direct"))
            continue
        order_targets = [
            grain for grain in direct_grains
            if grain[0] == row.business_date and grain[1] == row.currency and grain[2] == row.external_order_id
        ] if row.external_order_id else []
        targets = order_targets or [
            grain for grain in direct_grains
            if grain[0] == row.business_date and grain[1] == row.currency
        ]
        method = "order_sales_ratio" if order_targets else "shop_day_sales_ratio"
        if not targets:
            item_key = f"UNALLOCATED-{row.source_key[:24]}"
            expanded.append((row, _grain(row, item_key), _money(row.signed_amount), "unallocated"))
            continue
        targets = sorted(set(targets), key=str)
        amounts = _split_amount(_money(row.signed_amount), targets, [sales_weights[target] for target in targets])
        expanded.extend((row, target, amount, method) for target, amount in zip(targets, amounts))

    grouped = defaultdict(list)
    for entry in expanded:
        grouped[entry[1]].append(entry)

    result = []
    for grain, entries in grouped.items():
        business_date, currency, external_order_id, item_key = grain
        source = next((entry[0] for entry in entries if _item_key(entry[0]) == item_key), entries[0][0])
        item = source.sales_order_item
        amounts = {field: Decimal("0") for field in AMOUNT_FIELDS}
        unknown_names = set()
        methods = set()
        details = []
        source_keys = []
        for row, _grain_value, amount, method in entries:
            field = FEE_COLUMNS.get((row.raw_fee_name or "").strip().lower(), "other_fee")
            amounts[field] += amount
            if field == "other_fee":
                unknown_names.add(row.raw_fee_name)
            methods.add(method)
            source_keys.append(row.source_key)
            details.append({
                "fee_name": row.raw_fee_name,
                "amount": str(amount),
                "method": method,
                "source_key": row.source_key,
            })
        for field in amounts:
            amounts[field] = _money(amounts[field])
        fee_total = _money(sum((value for field, value in amounts.items() if field not in {"item_price_credit", "reversal_item_price"}), Decimal("0")))
        income_key = _hash({
            "tenant": source.tenant_id,
            "store": source.store_id,
            "date": business_date,
            "currency": currency,
            "order": external_order_id,
            "item": item_key,
        })
        result.append({
            "tenant_id": source.tenant_id,
            "store_id": source.store_id,
            "authorization_id": source.authorization_id,
            "source_run_id": max(entry[0].source_run_id for entry in entries),
            "income_key": income_key,
            "site": source.store.country_code,
            "transaction_date": business_date,
            "transaction_month": business_date.strftime("%Y-%m"),
            "currency": currency,
            "external_order_id": external_order_id,
            "external_order_item_id": item_key,
            "seller_sku": source.seller_sku or (item.seller_sku if item else ""),
            "lazada_sku": source.platform_variant_id or (item.platform_variant_id if item else ""),
            "order_item_status": item.raw_line_status if item else "",
            "item_name": item.item_name_snapshot if item else "",
            **amounts,
            "sales_amount": amounts["item_price_credit"],
            "refund_amount": amounts["reversal_item_price"],
            "platform_fee_total": fee_total,
            "net_income": _money(sum(amounts.values(), Decimal("0"))),
            "source_row_count": len(entries),
            "allocation_methods": sorted(methods),
            "unknown_fee_names": sorted(name for name in unknown_names if name),
            "fee_details": details,
            "source_hash": _hash(sorted(source_keys)),
        })
    return result


@transaction.atomic
def rebuild_lazada_finance_wide(*, tenant, store, business_dates=None):
    queryset = PlatformFinanceTransaction.objects.filter(tenant=tenant, store=store).select_related(
        "store", "sales_order_item"
    )
    dates = sorted(set(business_dates or queryset.values_list("business_date", flat=True)))
    if not dates:
        return 0
    queryset = queryset.filter(business_date__in=dates)
    payloads = build_lazada_finance_wide_rows(queryset)
    LazadaFinanceWide.objects.filter(tenant=tenant, store=store, transaction_date__in=dates).delete()
    LazadaFinanceWide.objects.bulk_create(LazadaFinanceWide(**payload) for payload in payloads)
    return len(payloads)


__all__ = ["FEE_COLUMNS", "build_lazada_finance_wide_rows", "rebuild_lazada_finance_wide"]
