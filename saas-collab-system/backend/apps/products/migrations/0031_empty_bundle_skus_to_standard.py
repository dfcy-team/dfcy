from django.db import migrations
from django.db.models import Exists, OuterRef


def convert_empty_bundles(apps, schema_editor):
    alias = schema_editor.connection.alias
    sku = apps.get_model("products", "ProductSKU")
    component = apps.get_model("products", "ProductBundleComponent")
    components = component.objects.using(alias).filter(bundle_sku_id=OuterRef("pk"))
    sku.objects.using(alias).filter(product_type="bundle").filter(
        ~Exists(components)
    ).update(product_type="standard")


class Migration(migrations.Migration):
    dependencies = [("products", "0030_productsku_product_type")]
    operations = [migrations.RunPython(convert_empty_bundles, migrations.RunPython.noop)]
