import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0002_platformfinancetransaction"),
        ("integrations", "0030_syncrun_queued_state"),
        ("masterdata", "0014_country_exchange_rate"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="LazadaFinanceWide",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("income_key", models.CharField(max_length=64)),
                ("site", models.CharField(max_length=20)),
                ("transaction_date", models.DateField()),
                ("transaction_month", models.CharField(max_length=7)),
                ("currency", models.CharField(max_length=8)),
                ("external_order_id", models.CharField(blank=True, max_length=191)),
                ("external_order_item_id", models.CharField(max_length=191)),
                ("seller_sku", models.CharField(blank=True, max_length=191)),
                ("lazada_sku", models.CharField(blank=True, max_length=191)),
                ("order_item_status", models.CharField(blank=True, max_length=80)),
                ("item_name", models.CharField(blank=True, max_length=240)),
                *[
                    (name, models.DecimalField(decimal_places=4, default=0, max_digits=20))
                    for name in (
                        "item_price_credit", "reversal_item_price", "commission", "payment_fee",
                        "payment_fee_credit", "reversal_commission", "free_shipping_max_fee",
                        "reversal_free_shipping_max_fee", "shipping_fee_refund_to_customer",
                        "shipping_fee_voucher_refund_to_laz", "sponsored_affiliates",
                        "promotional_charges_vouchers", "reversal_promotional_charges_vouchers",
                        "promotional_charges_flexi_combo", "reversal_promotional_charges_flexi_combo",
                        "lazcoins_discount", "reversal_lazcoins_discount",
                        "lazcoins_discount_promotion_fee", "reversal_lazcoins_discount_promotion_fee",
                        "order_processing_fee", "reversal_order_processing_fee", "spa_program_fee",
                        "reversal_spa_program_fee", "wrong_shipping_fee_adjustment", "withholding_tax",
                        "other_fee", "sales_amount", "refund_amount", "platform_fee_total", "net_income",
                    )
                ],
                ("source_row_count", models.PositiveIntegerField(default=0)),
                ("allocation_methods", models.JSONField(default=list)),
                ("unknown_fee_names", models.JSONField(default=list)),
                ("fee_details", models.JSONField(default=list)),
                ("source_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("authorization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="finance_wide_rows", to="integrations.marketplacestoreauthorization")),
                ("source_run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="finance_wide_rows", to="integrations.syncrun")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lazada_finance_wide_rows", to="masterdata.storemaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lazada_finance_wide_rows", to="tenants.tenant")),
            ],
            options={
                "db_table": "lazada_finance_wide",
                "ordering": ["-transaction_date", "store_id", "external_order_item_id"],
                "indexes": [
                    models.Index(fields=["tenant", "store", "transaction_date"], name="idx_lz_wide_store_date"),
                    models.Index(fields=["tenant", "external_order_id"], name="idx_lz_wide_order"),
                    models.Index(fields=["tenant", "seller_sku"], name="idx_lz_wide_sku"),
                ],
                "constraints": [models.UniqueConstraint(fields=("tenant", "income_key"), name="uniq_lazada_income_key")],
            },
        ),
    ]
