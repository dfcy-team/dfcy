"""Choose a platform-owned image for the exact variant. Never download or write a SKU image."""
from urllib.parse import urlsplit


CDN_HOSTS = {
    "shopee": ("susercontent.com", "shopeemobile.com", "shopee.sg", "shopee.ph", "shopee.com.ph",
               "shopee.com.my", "shopee.co.th", "shopee.vn", "shopee.co.id", "shopee.com.br",
               "shopee.tw", "shopee.com.tw", "shopee.com.mx", "shopee.com.co", "shopee.cl"),
    "lazada": ("slatic.net", "lazcdn.com", "alicdn.com"),
    "tiktok": ("ibyteimg.com", "byteimg.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "ibytedtos.com"),
}


def safe_platform_image(value, platform):
    if not isinstance(value, str) or len(value) > 2048 or "\\" in value or any(ord(c) < 32 for c in value):
        return ""
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in (None, 443)
                or not any(host == domain or host.endswith("." + domain) for domain in CDN_HOSTS.get(platform, ()))):
            return ""
    except ValueError:
        return ""
    return value.strip()


def normalized_image_fields(record, platform):
    if "platform_image_url" not in record:
        return {}
    url, source = record["platform_image_url"], record.get("platform_image_source", "")
    if url == "":
        return {"platform_image_url": "", "platform_image_source": ""}
    safe = safe_platform_image(url, platform)
    if not safe or source not in {"variant", "product"}:
        return {}  # An invalid or absent optional field must not erase a known image.
    return {"platform_image_url": safe, "platform_image_source": source}


def _choose(platform, variant, product, *, empty=False):
    for source, candidates in (("variant", variant), ("product", product)):
        for candidate in candidates:
            safe = safe_platform_image(candidate, platform)
            if safe:
                return {"platform_image_url": safe, "platform_image_source": source}
    return {"platform_image_url": "", "platform_image_source": ""} if empty and not variant and not product else {}


def shopee_image(product, model=None, body=None):
    block = product.get("image")
    main = block.get("image_url_list") if isinstance(block, dict) else None
    main = main if isinstance(main, list) else None
    variants = []
    body, model = body or {}, model or {}
    tiers = body.get("standardise_tier_variation") or body.get("tier_variation") or []
    indexes = model.get("tier_index") or []
    if isinstance(tiers, list) and isinstance(indexes, list):
        for position, tier in enumerate(tiers):
            if not isinstance(tier, dict) or position >= len(indexes):
                continue
            options = tier.get("variation_option_list", tier.get("option_list"))
            index = indexes[position]
            if not isinstance(options, list) or type(index) is not int or not 0 <= index < len(options):
                continue
            option = options[index]
            if isinstance(option, dict):
                image = option.get("image")
                url = option.get("image_url") or (image.get("image_url") if isinstance(image, dict) else None)
                if url:
                    variants.append(url)
    return _choose("shopee", variants, main or [], empty=main == [])


def _lazada_urls(value):
    if isinstance(value, dict):
        value = value.get("Image")
    return value if isinstance(value, list) else None


def lazada_image(product, sku):
    variant = _lazada_urls(sku.get("Images"))
    main = _lazada_urls(product.get("images", product.get("Images")))
    return _choose("lazada", variant or [], main or [], empty=main == [] or variant == [] and main is None)


def tiktok_image(product, sku):
    main = product.get("main_images")
    product_urls, variant_urls = [], []
    if isinstance(main, list):
        for image in main:
            if isinstance(image, dict) and isinstance(image.get("urls"), list):
                product_urls.extend(image["urls"])
    attributes = sku.get("sales_attributes")
    if isinstance(attributes, list):
        for attribute in attributes:
            image = attribute.get("sku_img") if isinstance(attribute, dict) else None
            if isinstance(image, dict) and isinstance(image.get("urls"), list):
                variant_urls.extend(image["urls"])
    return _choose("tiktok", variant_urls, product_urls, empty=main == [])
