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

# Warehouse types are business classifications rather than concrete API
# providers.  Keep connector discovery explicit so a warehouse row cannot be
# treated as connected merely because its business type is known.
WAREHOUSE_CONNECTOR_UNMAPPED = "UNMAPPED"
WAREHOUSE_CONNECTOR_REGISTRY = {
    "jifeng_wms": {
        "name": "极风 WMS",
        "status": "ACTIVE",
        "hint": "已按平台编码或名称识别为极风 WMS，支持库存 API 接入。",
    },
}
WAREHOUSE_CATEGORY_HINT = "业务分类，连接器按具体服务商编码或名称识别。"

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
    is_warehouse_category = value in WAREHOUSE_SERVICE
    status = (
        WAREHOUSE_CONNECTOR_UNMAPPED
        if is_warehouse_category
        else "ACTIVE" if value in {"shopee", "tiktok"}
        else "TESTING" if value == "lazada"
        else "NOT_IMPLEMENTED"
    )
    return {
        "value": value,
        "canonical_code": CANONICAL_CODES.get(value, value.upper()),
        "label": _label(value),
        "platform_category": _category(value),
        "is_business_category": is_warehouse_category,
        "option_group": "仓储服务分类" if is_warehouse_category else "销售渠道/独立站" if _category(value) in {"MARKETPLACE", "SOCIAL_COMMERCE", "DTC_STORE"} else "ERP/其他",
        "connector_key": "" if is_warehouse_category else value if status != "NOT_IMPLEMENTED" else "",
        "connector_name": "按具体服务商识别" if is_warehouse_category else _label(value),
        "connector_hint": WAREHOUSE_CATEGORY_HINT if is_warehouse_category else "",
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


def _compact_identifier(value):
    """Normalize a human/code identifier for the small local alias set."""
    return "".join(character for character in str(value or "").strip().lower() if character.isalnum())


def resolve_platform_connector(*, platform_type="", code="", name=""):
    """Resolve the concrete connector represented by a platform master row."""
    normalized_type = normalize_platform_code(platform_type) or str(platform_type or "").strip().lower()
    item = platform_catalog_item(normalized_type)
    if normalized_type in WAREHOUSE_SERVICE:
        provider = ""
        try:
            from apps.integrations.platform_schema_service import integration_platform_key

            provider = integration_platform_key(platform_type=normalized_type, code=code, name=name)
        except (ImportError, ModuleNotFoundError):
            provider = ""
        if not provider and any(_compact_identifier(value) in {"myjf", "马来极风"} for value in (code, name)):
            provider = "jifeng_wms"
        metadata = WAREHOUSE_CONNECTOR_REGISTRY.get(provider)
        if metadata:
            return {
                "connector_key": provider,
                "connector_name": metadata["name"],
                "connector_status": metadata["status"],
                "connector_hint": metadata["hint"],
            }
        return {
            "connector_key": "",
            "connector_name": "待识别服务商",
            "connector_status": WAREHOUSE_CONNECTOR_UNMAPPED,
            "connector_hint": "这是仓储业务分类，不是单一连接器；请维护具体服务商编码和名称，匹配后才可进行对应 API 接入。",
        }

    if item:
        status = item["connector_status"]
        return {
            "connector_key": item.get("connector_key", "") or (normalized_type if status != "NOT_IMPLEMENTED" else ""),
            "connector_name": item.get("connector_name") or item.get("label", ""),
            "connector_status": status,
            "connector_hint": item.get("connector_hint", ""),
        }
    return {
        "connector_key": "",
        "connector_name": "待识别平台",
        "connector_status": "UNMAPPED",
        "connector_hint": "平台类型未在目录中匹配，请先维护受支持的平台类型。",
    }


def platform_connector_resolution(*, platform_type="", code="", name=""):
    """Backward-compatible descriptive alias for record-level resolution."""
    return resolve_platform_connector(platform_type=platform_type, code=code, name=name)
