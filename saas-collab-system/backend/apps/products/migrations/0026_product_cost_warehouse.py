from django.db import migrations, models
import django.db.models.deletion


def replace_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("ALTER TABLE products_productcostversion DROP CONSTRAINT IF EXISTS exclude_confirmed_product_cost_overlap")
    for name, predicate in (
        ("exclude_cost_warehouse_overlap", "status = 'confirmed' AND warehouse_id IS NOT NULL"),
        ("exclude_cost_legacy_overlap", "status = 'confirmed' AND warehouse_id IS NULL"),
    ):
        dimensions = "tenant_id WITH =, sku_id WITH =, "
        if "warehouse_overlap" in name:
            dimensions += "warehouse_id WITH =, "
        schema_editor.execute(
            f"ALTER TABLE products_productcostversion ADD CONSTRAINT {name} EXCLUDE USING gist ("
            f"{dimensions}tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&"
            f") WHERE ({predicate})"
        )


def restore_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name in ("exclude_cost_warehouse_overlap", "exclude_cost_legacy_overlap"):
        schema_editor.execute(f"ALTER TABLE products_productcostversion DROP CONSTRAINT IF EXISTS {name}")
    schema_editor.execute(
        "ALTER TABLE products_productcostversion ADD CONSTRAINT exclude_confirmed_product_cost_overlap "
        "EXCLUDE USING gist (tenant_id WITH =, sku_id WITH =, "
        "tstzrange(effective_from, COALESCE(effective_to, 'infinity'::timestamptz), '[)') WITH &&) "
        "WHERE (status = 'confirmed')"
    )


class Migration(migrations.Migration):
    dependencies = [("products", "0025_bundle_cost_allocation_ratio"), ("masterdata", "0011_merge_warehouse_and_platform_site_branches")]

    operations = [
        migrations.AddField(
            model_name="productcostversion", name="warehouse",
            field=models.ForeignKey(to="masterdata.warehousemaster", on_delete=django.db.models.deletion.PROTECT,
                                    related_name="product_cost_versions", null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="productcostversion",
            index=models.Index(fields=["tenant", "warehouse", "sku", "status", "effective_from"], name="idx_cost_warehouse_asof"),
        ),
        migrations.RunPython(replace_exclusion, restore_exclusion),
    ]
