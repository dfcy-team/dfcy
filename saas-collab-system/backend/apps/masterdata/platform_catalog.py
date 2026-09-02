"""Canonical sales-channel catalog; connector availability is intentionally separate."""

P0 = ("shopee", "tiktok", "lazada", "temu", "amazon", "wildberries", "ozon")
P1 = (
    "aliexpress", "ebay", "walmart", "shein", "mercado_libre", "yandex_market",
    "allegro", "kaufland", "zalando", "noon", "coupang", "shopify",
)
P2 = (
    "etsy", "zalora", "daraz", "cdiscount", "otto", "bol", "onbuy", "trendyol",
    "namshi", "flipkart", "myntra", "rakuten_jp", "yahoo_jp", "woocommerce",
    "shopline", "shoplazza",
)
P3 = (
    "target_plus", "wayfair", "fnac_darty", "manomano", "megamarket", "meesho",
    "jumia", "magalu", "americanas", "bigcommerce", "magento", "wix",
    "custom_store", "regional_other",
)
# Warehouse service platform types are master-data values too.  Keeping them
# in the same catalog makes the catalog the single source for platform
# selectors while preserving the existing warehouse model choices.
WAREHOUSE_SERVICE = ("warehouse_owned", "warehouse_third_party", "warehouse_platform")

LABELS = {
    "tiktok": "TikTok Shop", "temu": "Temu", "amazon": "Amazon",
    "wildberries": "Wildberries", "ozon": "Ozon", "aliexpress": "AliExpress",
    "ebay": "eBay", "walmart": "Walmart Marketplace", "shein": "SHEIN Marketplace",
    "mercado_libre": "Mercado Libre", "yandex_market": "Yandex Market",
    "kaufland": "Kaufland Global Marketplace", "noon": "noon", "shopify": "Shopify",
    "etsy": "Etsy", "cdiscount": "Cdiscount", "otto": "OTTO", "bol": "bol.",
    "onbuy": "OnBuy", "rakuten_jp": "Rakuten Japan", "yahoo_jp": "Yahoo! Japan",
    "woocommerce": "WooCommerce", "shopline": "SHOPLINE", "shoplazza": "SHOPLAZZA",
    "target_plus": "Target Plus", "fnac_darty": "Fnac Darty", "manomano": "ManoMano",
    "megamarket": "MegaMarket", "magalu": "Magalu", "bigcommerce": "BigCommerce",
    "custom_store": "Custom Store", "regional_other": "Regional Other",
    "bigseller": "BigSeller", "other": "Other",
    "warehouse_owned": "自营仓服务", "warehouse_third_party": "三方仓服务", "warehouse_platform": "平台仓服务",
}
CANONICAL_CODES = {"tiktok": "TIKTOK_SHOP"}
ALIASES = {
    "shopee": ("SHP",), "tiktok": ("TK", "TIKTOK", "TIKTOKSHOP", "TIKTOK_SHOP"),
    "wildberries": ("WB",), "mercado_libre": ("MELI", "MERCADOLIBRE"),
    "yandex_market": ("YANDEXMARKET",), "woocommerce": ("WOO",),
    "bigseller": ("BIG_SELLER",),
}


def _label(value):
    return LABELS.get(value, value.replace("_", " ").title())


def _category(value):
    if value in WAREHOUSE_SERVICE:
        return "WAREHOUSE_SERVICE"
    if value == "tiktok":
        return "SOCIAL_COMMERCE"
    if value in {"shopify", "woocommerce", "shopline", "shoplazza", "bigcommerce", "magento", "wix", "custom_store"}:
        return "DTC_STORE"
    if value == "bigseller":
        return "ERP_CHANNEL"
    if value in {"regional_other", "other"}:
        return "OTHER"
    return "MARKETPLACE"


def _entry(value, priority):
    status = "ACTIVE" if value in {"shopee", "tiktok"} else "TESTING" if value == "lazada" else "NOT_IMPLEMENTED"
    return {
        "value": value,
        "canonical_code": CANONICAL_CODES.get(value, value.upper()),
        "label": _label(value),
        "platform_category": _category(value),
        "priority_level": priority,
        "default_integration_mode": (
            "HYBRID" if value == "bigseller"
            else "MANUAL" if value in {"custom_store", "regional_other", "other"}
            else "OFFICIAL_API"
        ),
        "connector_status": status,
        "enabled_by_default": priority == "P0" and status != "NOT_IMPLEMENTED",
        "aliases": list(ALIASES.get(value, ())),
    }


PLATFORM_CATALOG = tuple(
    [_entry(value, "P0") for value in P0]
    + [_entry(value, "P1") for value in P1]
    + [_entry(value, "P2") for value in P2]
    + [_entry(value, "P3") for value in P3]
    + [_entry(value, "P3") for value in WAREHOUSE_SERVICE]
    + [_entry("bigseller", "LEGACY"), _entry("other", "P3")]
)
PLATFORM_BY_VALUE = {item["value"]: item for item in PLATFORM_CATALOG}


def _alias_key(value):
    return "".join(character for character in str(value or "").upper() if character.isalnum())


ALIAS_TO_VALUE = {}
for item in PLATFORM_CATALOG:
    for alias in (item["value"], item["canonical_code"], *item["aliases"]):
        ALIAS_TO_VALUE[_alias_key(alias)] = item["value"]


def normalize_platform_code(value):
    """Return the compatible internal value for a known code/alias, else an empty string."""
    return ALIAS_TO_VALUE.get(_alias_key(value), "")


def platform_catalog_item(value):
    return PLATFORM_BY_VALUE.get(normalize_platform_code(value) or str(value or "").strip().lower())
