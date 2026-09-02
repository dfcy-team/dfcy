from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class StatusChoices(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class SupplierStatusChoices(models.TextChoices):
    ACTIVE = "active", "Active"
    TRIAL = "trial", "Trial cooperation"
    INACTIVE = "inactive", "Inactive"


class PlatformMaster(models.Model):
    class PlatformType(models.TextChoices):
        BIGSELLER = "bigseller", "BigSeller"
        SHOPEE = "shopee", "Shopee"
        TIKTOK = "tiktok", "TikTok Shop"
        LAZADA = "lazada", "LAZADA"
        TEMU = "temu", "TEMU"
        WAREHOUSE_OWNED = "warehouse_owned", "自营仓服务"
        WAREHOUSE_THIRD_PARTY = "warehouse_third_party", "三方仓服务"
        WAREHOUSE_PLATFORM = "warehouse_platform", "平台仓服务"
        AMAZON = "amazon", "Amazon"
        WILDBERRIES = "wildberries", "Wildberries"
        OZON = "ozon", "Ozon"
        ALIEXPRESS = "aliexpress", "AliExpress"
        EBAY = "ebay", "eBay"
        WALMART = "walmart", "Walmart Marketplace"
        SHEIN = "shein", "SHEIN Marketplace"
        MERCADO_LIBRE = "mercado_libre", "Mercado Libre"
        YANDEX_MARKET = "yandex_market", "Yandex Market"
        ALLEGRO = "allegro", "Allegro"
        KAUFLAND = "kaufland", "Kaufland Global Marketplace"
        ZALANDO = "zalando", "Zalando"
        NOON = "noon", "noon"
        COUPANG = "coupang", "Coupang"
        SHOPIFY = "shopify", "Shopify"
        ETSY = "etsy", "Etsy"
        ZALORA = "zalora", "Zalora"
        DARAZ = "daraz", "Daraz"
        CDISCOUNT = "cdiscount", "Cdiscount"
        OTTO = "otto", "OTTO"
        BOL = "bol", "bol."
        ONBUY = "onbuy", "OnBuy"
        TRENDYOL = "trendyol", "Trendyol"
        NAMSHI = "namshi", "Namshi"
        FLIPKART = "flipkart", "Flipkart"
        MYNTRA = "myntra", "Myntra"
        RAKUTEN_JP = "rakuten_jp", "Rakuten Japan"
        YAHOO_JP = "yahoo_jp", "Yahoo! Japan"
        WOOCOMMERCE = "woocommerce", "WooCommerce"
        SHOPLINE = "shopline", "SHOPLINE"
        SHOPLAZZA = "shoplazza", "SHOPLAZZA"
        TARGET_PLUS = "target_plus", "Target Plus"
        WAYFAIR = "wayfair", "Wayfair"
        FNAC_DARTY = "fnac_darty", "Fnac Darty"
        MANOMANO = "manomano", "ManoMano"
        MEGAMARKET = "megamarket", "MegaMarket"
        MEESHO = "meesho", "Meesho"
        JUMIA = "jumia", "Jumia"
        MAGALU = "magalu", "Magalu"
        AMERICANAS = "americanas", "Americanas"
        BIGCOMMERCE = "bigcommerce", "BigCommerce"
        MAGENTO = "magento", "Magento"
        WIX = "wix", "Wix"
        CUSTOM_STORE = "custom_store", "Custom Store"
        REGIONAL_OTHER = "regional_other", "Regional Other"
        OTHER = "other", "Other"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_masters")
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    platform_type = models.CharField(max_length=30, choices=PlatformType.choices)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_platform_master_code")]


class PlatformSiteMaster(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_site_masters")
    platform = models.ForeignKey(PlatformMaster, on_delete=models.PROTECT, related_name="platform_sites")
    site_code = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    country_code = models.CharField(max_length=8)
    region_code = models.CharField(max_length=32, blank=True, default="")
    currency_code = models.CharField(max_length=8, blank=True, default="")
    timezone = models.CharField(max_length=60, default="UTC")
    language_codes = models.JSONField(default=list, blank=True)
    api_region = models.CharField(max_length=60, blank=True, default="")
    api_base_url = models.URLField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform_id", "site_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "site_code"], name="uniq_platform_site_code"
            )
        ]

    def clean(self):
        if self.platform_id and self.tenant_id != self.platform.tenant_id:
            raise ValidationError({"platform": "Platform site tenant must match platform tenant."})


class StoreMaster(models.Model):
    class BusinessModel(models.TextChoices):
        LOCAL = "local", "Local"
        CROSS_BORDER = "cross_border", "Cross border"
        FULL_MANAGED = "full_managed", "Full managed"
        SEMI_MANAGED = "semi_managed", "Semi managed"
        OTHER = "other", "Other"

    FULFILLMENT_MODES = {
        "platform_fulfillment", "third_party_warehouse", "local_self_fulfillment",
        "cross_border_direct", "hybrid",
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="store_masters")
    platform = models.ForeignKey(PlatformMaster, on_delete=models.PROTECT, related_name="stores")
    platform_site = models.ForeignKey(
        PlatformSiteMaster, on_delete=models.PROTECT, related_name="stores", null=True, blank=True,
    )
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    external_store_id = models.CharField(max_length=160, blank=True, default="")
    seller_entity_id = models.CharField(max_length=160, blank=True, default="")
    business_model = models.CharField(
        max_length=30, choices=BusinessModel.choices, default=BusinessModel.OTHER,
    )
    fulfillment_modes = models.JSONField(default=list, blank=True)
    settlement_currency = models.CharField(max_length=8, blank=True, default="")
    # Platform-facing archive metadata. All references are tenant-scoped by
    # serializer validation; nullable keeps existing records deployable.
    platform_store_name = models.CharField(max_length=160, blank=True, default="")
    category = models.ForeignKey(
        "products.ProductCategory", on_delete=models.PROTECT,
        related_name="store_masters", null=True, blank=True,
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="operated_store_masters", null=True, blank=True,
    )
    bd = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="bd_store_masters", null=True, blank=True,
    )
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="led_store_masters", null=True, blank=True,
    )
    is_connected = models.BooleanField(default=False)
    # The 战斧客户端 value is a text/account reference supplied by operations;
    # it is intentionally not an integration enum or credential field.
    tactical_client = models.CharField(max_length=160, blank=True, default="")
    country_code = models.CharField(max_length=8)
    currency = models.CharField(max_length=8)
    timezone = models.CharField(max_length=60, default="UTC")
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_store_master_code")]

    def clean(self):
        errors = {}
        if self.platform_site_id:
            if self.platform_site.tenant_id != self.tenant_id:
                errors["platform_site"] = "Platform site tenant must match store tenant."
            elif self.platform_site.platform_id != self.platform_id:
                errors["platform_site"] = "Platform site must belong to the store platform."
        modes = self.fulfillment_modes or []
        if not isinstance(modes, list) or any(mode not in self.FULFILLMENT_MODES for mode in modes):
            errors["fulfillment_modes"] = "Unsupported fulfillment mode."
        if errors:
            raise ValidationError(errors)


class CountrySiteMaster(models.Model):
    """Tenant-owned country information archive.

    ``sites`` is the stable resource name kept for API compatibility with the
    original country/platform records.  ``platform`` remains a nullable legacy
    hint for existing product-development and listing imports; new consumers
    should use the country name, code, currency and timezone fields.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="country_site_masters")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    country_code = models.CharField(max_length=8)
    platform = models.CharField(max_length=60, blank=True, null=True, default=None)
    currency = models.CharField(max_length=8, blank=True, default="")
    timezone = models.CharField(max_length=60, blank=True, default="UTC")
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_country_site_master_code")]

    def __str__(self):
        return f"{self.code} ({self.name})"


WAREHOUSE_SERVICE_PLATFORM_TYPES = frozenset(
    {
        PlatformMaster.PlatformType.WAREHOUSE_OWNED,
        PlatformMaster.PlatformType.WAREHOUSE_THIRD_PARTY,
        PlatformMaster.PlatformType.WAREHOUSE_PLATFORM,
    }
)

WAREHOUSE_TYPE_TO_PLATFORM_TYPE = {
    "owned": PlatformMaster.PlatformType.WAREHOUSE_OWNED,
    "third_party": PlatformMaster.PlatformType.WAREHOUSE_THIRD_PARTY,
    "platform": PlatformMaster.PlatformType.WAREHOUSE_PLATFORM,
}


class WarehouseMaster(models.Model):
    class WarehouseType(models.TextChoices):
        OWNED = "owned", "Owned"
        THIRD_PARTY = "third_party", "Third party"
        PLATFORM = "platform", "Platform"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="warehouse_masters")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    country_code = models.CharField(max_length=8)
    warehouse_type = models.CharField(max_length=30, choices=WarehouseType.choices)
    service_platform = models.ForeignKey(
        PlatformMaster,
        on_delete=models.PROTECT,
        related_name="service_warehouses",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_warehouse_master_code")]


class SupplierMaster(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="supplier_masters")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    contact_alias = models.CharField(max_length=80, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=20, choices=SupplierStatusChoices.choices, default=SupplierStatusChoices.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_supplier_master_code")]
