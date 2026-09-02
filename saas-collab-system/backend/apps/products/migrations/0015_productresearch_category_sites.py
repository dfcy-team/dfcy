from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("products", "0014_alter_productlegacyitem_package_volume_and_more"), ("masterdata", "0003_countrysitemaster")]

    operations = [
        migrations.AddField(
            model_name="productresearch",
            name="category_node",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="research_items", to="products.productcategory"),
        ),
        migrations.AddField(
            model_name="productresearch",
            name="target_sites",
            field=models.ManyToManyField(blank=True, related_name="product_research_items", to="masterdata.countrysitemaster"),
        ),
    ]
