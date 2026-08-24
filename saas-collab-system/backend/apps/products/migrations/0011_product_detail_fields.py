from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0010_product_purchase_price")]

    operations = [
        migrations.AddField(model_name="productsku", name="unit", field=models.CharField(blank=True, max_length=30, null=True)),
        migrations.AddField(model_name="productsku", name="image_url", field=models.CharField(blank=True, max_length=500, null=True)),
        migrations.AddField(model_name="productsku", name="package_length_cm", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productsku", name="package_width_cm", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productsku", name="package_height_cm", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productsku", name="origin_country", field=models.CharField(blank=True, max_length=80, null=True)),
        migrations.AddField(model_name="productsku", name="hs_code", field=models.CharField(blank=True, max_length=20, null=True)),
        migrations.AddField(model_name="productsku", name="product_description", field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="unit", field=models.CharField(blank=True, max_length=30, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="image_url", field=models.CharField(blank=True, max_length=500, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="package_weight", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="package_volume", field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="package_length_cm", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="package_width_cm", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="package_height_cm", field=models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="origin_country", field=models.CharField(blank=True, max_length=80, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="hs_code", field=models.CharField(blank=True, max_length=20, null=True)),
        migrations.AddField(model_name="productlegacyitem", name="product_description", field=models.TextField(blank=True, null=True)),
        migrations.AddConstraint(model_name="productsku", constraint=models.CheckConstraint(condition=models.Q(package_weight__isnull=True) | models.Q(package_weight__gte=0), name="product_sku_package_weight_nonnegative")),
        migrations.AddConstraint(model_name="productsku", constraint=models.CheckConstraint(condition=models.Q(package_volume__isnull=True) | models.Q(package_volume__gte=0), name="product_sku_package_volume_nonnegative")),
        migrations.AddConstraint(model_name="productsku", constraint=models.CheckConstraint(condition=models.Q(package_length_cm__isnull=True) | models.Q(package_length_cm__gte=0), name="product_sku_package_length_nonnegative")),
        migrations.AddConstraint(model_name="productsku", constraint=models.CheckConstraint(condition=models.Q(package_width_cm__isnull=True) | models.Q(package_width_cm__gte=0), name="product_sku_package_width_nonnegative")),
        migrations.AddConstraint(model_name="productsku", constraint=models.CheckConstraint(condition=models.Q(package_height_cm__isnull=True) | models.Q(package_height_cm__gte=0), name="product_sku_package_height_nonnegative")),
        migrations.AddConstraint(model_name="productlegacyitem", constraint=models.CheckConstraint(condition=models.Q(package_weight__isnull=True) | models.Q(package_weight__gte=0), name="product_legacy_package_weight_nonnegative")),
        migrations.AddConstraint(model_name="productlegacyitem", constraint=models.CheckConstraint(condition=models.Q(package_volume__isnull=True) | models.Q(package_volume__gte=0), name="product_legacy_package_volume_nonnegative")),
        migrations.AddConstraint(model_name="productlegacyitem", constraint=models.CheckConstraint(condition=models.Q(package_length_cm__isnull=True) | models.Q(package_length_cm__gte=0), name="product_legacy_package_length_nonnegative")),
        migrations.AddConstraint(model_name="productlegacyitem", constraint=models.CheckConstraint(condition=models.Q(package_width_cm__isnull=True) | models.Q(package_width_cm__gte=0), name="product_legacy_package_width_nonnegative")),
        migrations.AddConstraint(model_name="productlegacyitem", constraint=models.CheckConstraint(condition=models.Q(package_height_cm__isnull=True) | models.Q(package_height_cm__gte=0), name="product_legacy_package_height_nonnegative")),
    ]
