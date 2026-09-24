import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("commerce", "0001_fact_tables_v1"),
        ("finance", "0001_initial"),
        ("integrations", "0030_syncrun_queued_state"),
        ("masterdata", "0014_country_exchange_rate"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformFinanceTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(default="lazada", max_length=30)),
                ("source_key", models.CharField(max_length=191)),
                ("external_transaction_id", models.CharField(blank=True, max_length=191)),
                ("external_order_id", models.CharField(blank=True, max_length=191)),
                ("external_order_item_id", models.CharField(blank=True, max_length=191)),
                ("seller_sku", models.CharField(blank=True, max_length=191)),
                ("platform_variant_id", models.CharField(blank=True, max_length=191)),
                ("raw_fee_name", models.CharField(max_length=191)),
                ("fee_code", models.CharField(max_length=40)),
                (
                    "fee_category",
                    models.CharField(
                        choices=[
                            ("income", "Income"),
                            ("platform_fee", "Platform fee"),
                            ("logistics_fee", "Logistics fee"),
                            ("discount", "Discount"),
                            ("refund", "Refund"),
                            ("tax", "Tax"),
                            ("adjustment", "Adjustment"),
                            ("other", "Other"),
                        ],
                        max_length=30,
                    ),
                ),
                ("raw_amount", models.DecimalField(decimal_places=4, max_digits=20)),
                ("signed_amount", models.DecimalField(decimal_places=4, max_digits=20)),
                ("currency", models.CharField(max_length=8)),
                ("occurred_at_utc", models.DateTimeField()),
                ("business_date", models.DateField()),
                (
                    "match_status",
                    models.CharField(
                        choices=[
                            ("matched", "Matched"),
                            ("order_only", "Order only"),
                            ("unmatched", "Unmatched"),
                            ("conflict", "Conflict"),
                        ],
                        max_length=20,
                    ),
                ),
                ("normalization_version", models.CharField(max_length=40)),
                ("payload_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "authorization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="finance_transactions",
                        to="integrations.marketplacestoreauthorization",
                    ),
                ),
                (
                    "raw_envelope",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="finance_transactions",
                        to="integrations.syncrawenvelope",
                    ),
                ),
                (
                    "sales_order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="finance_transactions",
                        to="commerce.salesorder",
                    ),
                ),
                (
                    "sales_order_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="finance_transactions",
                        to="commerce.salesorderitem",
                    ),
                ),
                (
                    "source_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="finance_transactions",
                        to="integrations.syncrun",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_finance_transactions",
                        to="masterdata.storemaster",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_finance_transactions",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "ordering": ["tenant_id", "store_id", "-occurred_at_utc", "-id"],
                "indexes": [
                    models.Index(fields=["tenant", "store", "business_date"], name="idx_fin_tx_store_date"),
                    models.Index(fields=["tenant", "external_order_id"], name="idx_fin_tx_order"),
                    models.Index(fields=["tenant", "fee_code", "business_date"], name="idx_fin_tx_fee_date"),
                    models.Index(fields=["source_run"], name="idx_fin_tx_run"),
                    models.Index(fields=["match_status"], name="idx_fin_tx_match"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "store", "source_key"), name="uniq_fin_tx_store_source"),
                    models.CheckConstraint(condition=models.Q(("platform", "lazada")), name="chk_fin_tx_lazada"),
                ],
            },
        ),
    ]
