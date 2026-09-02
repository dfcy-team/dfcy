from django.db import migrations, models


CHOICES = [
    ("bigseller", "BigSeller"), ("shopee", "Shopee"), ("tiktok", "TikTok Shop"),
    ("lazada", "LAZADA"), ("temu", "TEMU"), ("amazon", "Amazon"),
    ("wildberries", "Wildberries"), ("ozon", "Ozon"), ("aliexpress", "AliExpress"),
    ("ebay", "eBay"), ("walmart", "Walmart Marketplace"), ("shein", "SHEIN Marketplace"),
    ("mercado_libre", "Mercado Libre"), ("yandex_market", "Yandex Market"),
    ("allegro", "Allegro"), ("kaufland", "Kaufland Global Marketplace"),
    ("zalando", "Zalando"), ("noon", "noon"), ("coupang", "Coupang"),
    ("shopify", "Shopify"), ("etsy", "Etsy"), ("zalora", "Zalora"),
    ("daraz", "Daraz"), ("cdiscount", "Cdiscount"), ("otto", "OTTO"),
    ("bol", "bol."), ("onbuy", "OnBuy"), ("trendyol", "Trendyol"),
    ("namshi", "Namshi"), ("flipkart", "Flipkart"), ("myntra", "Myntra"),
    ("rakuten_jp", "Rakuten Japan"), ("yahoo_jp", "Yahoo! Japan"),
    ("woocommerce", "WooCommerce"), ("shopline", "SHOPLINE"),
    ("shoplazza", "SHOPLAZZA"), ("target_plus", "Target Plus"),
    ("wayfair", "Wayfair"), ("fnac_darty", "Fnac Darty"), ("manomano", "ManoMano"),
    ("megamarket", "MegaMarket"), ("meesho", "Meesho"), ("jumia", "Jumia"),
    ("magalu", "Magalu"), ("americanas", "Americanas"),
    ("bigcommerce", "BigCommerce"), ("magento", "Magento"), ("wix", "Wix"),
    ("custom_store", "Custom Store"), ("regional_other", "Regional Other"),
    ("other", "Other"),
]


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0008_merge_country_and_store_branches")]
    operations = [
        migrations.AlterField(
            model_name="platformmaster",
            name="platform_type",
            field=models.CharField(choices=CHOICES, max_length=30),
        ),
    ]
