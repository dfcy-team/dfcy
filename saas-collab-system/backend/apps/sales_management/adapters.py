from apps.integrations.sales_order_contract import normalize_sales_order_record


# Compatibility alias for callers created before the integration-owned contract.
# This function accepts canonical sales_order.v1 records, never raw platform payloads.
normalize_platform_order = normalize_sales_order_record


__all__ = ["normalize_platform_order", "normalize_sales_order_record"]
