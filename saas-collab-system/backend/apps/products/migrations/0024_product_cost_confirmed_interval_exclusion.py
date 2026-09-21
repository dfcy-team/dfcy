from django.db import migrations


CONSTRAINT = "exclude_confirmed_product_cost_overlap"


def add_postgres_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    schema_editor.execute(
        f"""
        ALTER TABLE products_productcostversion
        ADD CONSTRAINT {CONSTRAINT}
        EXCLUDE USING gist (
            tenant_id WITH =,
            sku_id WITH =,
            tstzrange(
                effective_from,
                COALESCE(effective_to, 'infinity'::timestamptz),
                '[)'
            ) WITH &&
        )
        WHERE (status = 'confirmed')
        """
    )


def remove_postgres_exclusion(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        f"ALTER TABLE products_productcostversion DROP CONSTRAINT IF EXISTS {CONSTRAINT}"
    )


class Migration(migrations.Migration):
    dependencies = [("products", "0023_productcostversion")]

    operations = [migrations.RunPython(add_postgres_exclusion, remove_postgres_exclusion)]
