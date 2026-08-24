from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("products", "0005_product_coding_and_bundles")]

    operations = [
        migrations.CreateModel(
            name="ProductAttribute",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=1)),
                ("name", models.CharField(max_length=80)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="product_attributes", to="tenants.tenant")),
            ],
            options={"ordering": ["tenant_id", "code"]},
        ),
        migrations.AddConstraint(
            model_name="productattribute",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_product_attribute_per_tenant"),
        ),
    ]
