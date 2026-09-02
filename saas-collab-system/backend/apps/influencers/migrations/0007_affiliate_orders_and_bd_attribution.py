import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0006_backfill_sample_pricing"),
        ("masterdata", "0001_initial"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AffiliateImportState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=40)),
                ("cursor", models.CharField(blank=True, max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[("idle", "Idle"), ("running", "Running"), ("failed", "Failed")],
                        default="idle",
                        max_length=20,
                    ),
                ),
                ("lease_token", models.CharField(blank=True, max_length=64)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("last_data_time", models.DateTimeField(blank=True, null=True)),
                ("last_source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("last_row_count", models.PositiveIntegerField(default=0)),
                ("last_rejected_count", models.PositiveIntegerField(default=0)),
                ("last_error_code", models.CharField(blank=True, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "source"],
            },
        ),
        migrations.CreateModel(
            name="AffiliateOrderSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=40)),
                ("source_row_key", models.CharField(max_length=64)),
                ("row_hash", models.CharField(max_length=64)),
                ("data_time", models.DateTimeField()),
                ("shop_name", models.CharField(blank=True, max_length=160)),
                ("shop_abbr", models.CharField(max_length=80)),
                ("site", models.CharField(max_length=32)),
                (
                    "order_id",
                    models.CharField(max_length=160),
                ),
                ("product_id", models.CharField(max_length=160)),
                ("product_name", models.CharField(blank=True, max_length=240)),
                ("sku_id", models.CharField(max_length=160)),
                ("product_price", models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True)),
                ("payment_amount", models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                (
                    "currency",
                    models.CharField(choices=[("CNY", "CNY"), ("PHP", "PHP"), ("MYR", "MYR"), ("THB", "THB"), ("USD", "USD")], max_length=3),
                ),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("fully_returned", models.CharField(default="否", max_length=20)),
                ("order_status", models.CharField(max_length=40)),
                ("creator_username", models.CharField(max_length=160)),
                ("creator_username_normalized", models.CharField(blank=True, db_index=True, default="", max_length=160)),
                ("actual_paid_commission", models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ("estimated_paid_commission", models.DecimalField(decimal_places=4, default=0, max_digits=20)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "store",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="influencer_affiliate_orders",
                        to="masterdata.storemaster",
                    ),
                ),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "data_time", "id"],
            },
        ),
        migrations.CreateModel(
            name="AffiliateOrderRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=40)),
                ("source_row_key", models.CharField(max_length=64)),
                ("revision_no", models.PositiveIntegerField()),
                ("before_hash", models.CharField(max_length=64)),
                ("after_hash", models.CharField(max_length=64)),
                ("before_values", models.JSONField(default=dict)),
                ("after_values", models.JSONField(default=dict)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "order_snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="influencers.affiliateordersnapshot",
                    ),
                ),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "source_row_key", "revision_no"],
            },
        ),
        migrations.CreateModel(
            name="BdSampleAttributionSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("creator_username", models.CharField(max_length=160)),
                ("shop_abbr", models.CharField(max_length=80)),
                ("site", models.CharField(max_length=32)),
                ("product_id", models.CharField(blank=True, max_length=160)),
                ("product_name", models.CharField(blank=True, max_length=240)),
                ("sku_id", models.CharField(blank=True, max_length=160)),
                ("sampled_at", models.DateTimeField()),
                ("shipped_at", models.DateTimeField(blank=True, null=True)),
                ("sample_status", models.CharField(max_length=20)),
                ("cost_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True)),
                (
                    "currency",
                    models.CharField(choices=[("CNY", "CNY"), ("PHP", "PHP"), ("MYR", "MYR"), ("THB", "THB"), ("USD", "USD")], max_length=3),
                ),
                ("pricing_status", models.CharField(max_length=20)),
                ("source", models.CharField(default="fulfillment", max_length=40)),
                ("legacy_inferred", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "fulfillment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_attribution_snapshot",
                        to="influencers.samplefulfillment",
                    ),
                ),
                (
                    "influencer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_sample_attribution_snapshots",
                        to="influencers.influencer",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_sample_attribution_snapshots",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_sample_attribution_snapshots",
                        to="masterdata.storemaster",
                    ),
                ),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "sampled_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="BdOrderAttributionSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order_id", models.CharField(max_length=160)),
                ("sku_id", models.CharField(max_length=160)),
                ("product_id", models.CharField(max_length=160)),
                (
                    "rule",
                    models.CharField(choices=[("strict", "Strict"), ("fallback", "Fallback")], max_length=20),
                ),
                ("rule_version", models.CharField(max_length=64)),
                ("attributed_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "influencer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_order_attribution_snapshots",
                        to="influencers.influencer",
                    ),
                ),
                (
                    "order_snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_attribution_snapshots",
                        to="influencers.affiliateordersnapshot",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bd_order_attribution_snapshots",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "sample_attribution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="order_attribution_snapshots",
                        to="influencers.bdsampleattributionsnapshot",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bd_order_attribution_snapshots",
                        to="masterdata.storemaster",
                    ),
                ),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "order_id", "sku_id", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="affiliateimportstate",
            constraint=models.UniqueConstraint(fields=("tenant", "source"), name="uniq_affiliate_import_state"),
        ),
        migrations.AddConstraint(
            model_name="affiliateordersnapshot",
            constraint=models.UniqueConstraint(
                fields=("tenant", "source", "source_row_key"),
                name="uniq_affiliate_order_source_row",
            ),
        ),
        migrations.AddConstraint(
            model_name="affiliateorderrevision",
            constraint=models.UniqueConstraint(
                fields=("tenant", "source", "source_row_key", "revision_no"),
                name="uniq_affiliate_order_revision",
            ),
        ),
        migrations.AddConstraint(
            model_name="bdorderattributionsnapshot",
            constraint=models.UniqueConstraint(
                fields=("tenant", "order_snapshot", "rule_version"),
                name="uniq_bd_order_attribution_version",
            ),
        ),
        migrations.AddIndex(
            model_name="affiliateimportstate",
            index=models.Index(fields=("tenant", "status", "lease_expires_at"), name="idx_aff_import_lease"),
        ),
        migrations.AddIndex(
            model_name="affiliateordersnapshot",
            index=models.Index(
                fields=("tenant", "data_time", "creator_username_normalized", "shop_abbr", "product_id"),
                name="idx_aff_order_date_creator",
            ),
        ),
        migrations.AddIndex(
            model_name="affiliateordersnapshot",
            index=models.Index(
                fields=("tenant", "creator_username_normalized", "shop_abbr", "site", "product_id", "data_time"),
                name="idx_aff_order_creator_shop",
            ),
        ),
        migrations.AddIndex(
            model_name="affiliateordersnapshot",
            index=models.Index(fields=("tenant", "shop_abbr", "site", "order_id", "sku_id"), name="idx_aff_order_shop_order_sku"),
        ),
        migrations.AddIndex(
            model_name="affiliateorderrevision",
            index=models.Index(fields=("tenant", "source_row_key", "revision_no"), name="idx_aff_order_revision_key"),
        ),
        migrations.AddIndex(
            model_name="bdsampleattributionsnapshot",
            index=models.Index(fields=("tenant", "creator_username", "shop_abbr", "product_id", "sampled_at"), name="idx_bd_sample_match"),
        ),
        migrations.AddIndex(
            model_name="bdsampleattributionsnapshot",
            index=models.Index(fields=("tenant", "owner", "sampled_at"), name="idx_bd_sample_owner_date"),
        ),
        migrations.AddIndex(
            model_name="bdorderattributionsnapshot",
            index=models.Index(fields=("tenant", "owner", "attributed_at"), name="idx_bd_order_owner_date"),
        ),
        migrations.AddIndex(
            model_name="bdorderattributionsnapshot",
            index=models.Index(fields=("tenant", "rule", "rule_version"), name="idx_bd_order_rule_version"),
        ),
    ]
