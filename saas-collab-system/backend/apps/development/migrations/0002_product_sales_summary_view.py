from django.db import migrations, models
import django.db.models.deletion


VIEW_NAME = "v_product_sales_summary"


def create_sales_summary_view(apps, schema_editor):
    quote = schema_editor.connection.ops.quote_name
    snapshot_table = quote("development_productsalessnapshot")
    view_name = quote(VIEW_NAME)
    vendor = schema_editor.connection.vendor

    if vendor == "mysql":
        date_30 = "DATE_SUB(CURRENT_DATE, INTERVAL 29 DAY)"
        date_90 = "DATE_SUB(CURRENT_DATE, INTERVAL 89 DAY)"
        days_listed = "DATEDIFF(CURRENT_DATE, MIN(snapshot_date)) + 1"
        summary_key = "CONCAT(product_id, ':', site)"
    elif vendor == "sqlite":
        date_30 = "DATE('now', '-29 day')"
        date_90 = "DATE('now', '-89 day')"
        days_listed = "CAST(JULIANDAY(DATE('now')) - JULIANDAY(MIN(snapshot_date)) + 1 AS INTEGER)"
        summary_key = "CAST(product_id AS TEXT) || ':' || site"
    else:
        date_30 = "CURRENT_DATE - INTERVAL '29 days'"
        date_90 = "CURRENT_DATE - INTERVAL '89 days'"
        days_listed = "(CURRENT_DATE - MIN(snapshot_date)) + 1"
        summary_key = "CAST(product_id AS TEXT) || ':' || site"

    schema_editor.execute(f"DROP VIEW IF EXISTS {view_name}")
    schema_editor.execute(
        f"""
        CREATE VIEW {view_name} AS
        SELECT
            {summary_key} AS summary_key,
            product_id,
            tenant_id,
            site,
            MIN(snapshot_date) AS first_sale_date,
            {days_listed} AS days_listed,
            COALESCE(SUM(CASE WHEN snapshot_date >= {date_30} THEN daily_sales_qty ELSE 0 END), 0) AS sales_30d_qty,
            COALESCE(SUM(CASE WHEN snapshot_date >= {date_30} THEN daily_sales_amount_usd ELSE 0 END), 0) AS sales_30d_amount_usd,
            COALESCE(SUM(CASE WHEN snapshot_date >= {date_90} THEN daily_sales_qty ELSE 0 END), 0) AS sales_90d_qty,
            COALESCE(SUM(CASE WHEN snapshot_date >= {date_90} THEN daily_sales_amount_usd ELSE 0 END), 0) AS sales_90d_amount_usd,
            COALESCE(AVG(daily_sales_qty), 0) AS avg_daily_sales_qty,
            COALESCE(SUM(ad_spend), 0) AS total_ad_spend,
            CASE
                WHEN COALESCE(SUM(ad_spend), 0) = 0 THEN NULL
                ELSE COALESCE(SUM(daily_sales_amount_usd), 0) / SUM(ad_spend)
            END AS roi
        FROM {snapshot_table}
        GROUP BY product_id, tenant_id, site
        """
    )


def drop_sales_summary_view(apps, schema_editor):
    schema_editor.execute(
        f"DROP VIEW IF EXISTS {schema_editor.connection.ops.quote_name(VIEW_NAME)}"
    )


class Migration(migrations.Migration):
    # MySQL cannot execute DROP/CREATE VIEW inside Django's atomic migration
    # wrapper because its DDL is not transactionally reversible.
    atomic = False

    dependencies = [("development", "0001_initial")]

    operations = [
        migrations.RunPython(create_sales_summary_view, drop_sales_summary_view),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ProductSalesSummary",
                    fields=[
                        ("summary_key", models.CharField(max_length=128, primary_key=True, serialize=False)),
                        (
                            "product",
                            models.ForeignKey(
                                db_column="product_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                related_name="sales_summary_projections",
                                to="products.productspu",
                            ),
                        ),
                        ("site", models.CharField(max_length=40)),
                        ("first_sale_date", models.DateField()),
                        ("days_listed", models.PositiveIntegerField()),
                        ("sales_30d_qty", models.PositiveIntegerField()),
                        ("sales_30d_amount_usd", models.DecimalField(decimal_places=2, max_digits=18)),
                        ("sales_90d_qty", models.PositiveIntegerField()),
                        ("sales_90d_amount_usd", models.DecimalField(decimal_places=2, max_digits=18)),
                        ("avg_daily_sales_qty", models.DecimalField(decimal_places=4, max_digits=18)),
                        ("total_ad_spend", models.DecimalField(decimal_places=2, max_digits=18)),
                        ("roi", models.DecimalField(decimal_places=4, max_digits=18, null=True)),
                        (
                            "tenant",
                            models.ForeignKey(
                                db_column="tenant_id",
                                on_delete=django.db.models.deletion.DO_NOTHING,
                                to="tenants.tenant",
                            ),
                        ),
                    ],
                    options={
                        "db_table": VIEW_NAME,
                        "ordering": ["tenant_id", "product_id", "site"],
                        "managed": False,
                    },
                )
            ],
            database_operations=[],
        ),
    ]
