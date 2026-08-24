import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("development", "0002_product_sales_summary_view"),
        ("products", "0013_productsku_product_name"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="developmentproject",
            name="category_node",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_projects",
                to="products.productcategory",
            ),
        ),
        migrations.CreateModel(
            name="DevelopmentProductArchive",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("archive_no", models.CharField(max_length=80)),
                ("product_name", models.CharField(max_length=200)),
                ("category", models.CharField(blank=True, max_length=120)),
                ("platform", models.CharField(default="internal", max_length=50)),
                ("site", models.CharField(default="internal", max_length=40)),
                ("inventory_mode", models.CharField(default="virtual", editable=False, max_length=20)),
                ("virtual_inventory_sku", models.CharField(max_length=100)),
                ("virtual_inventory_qty", models.PositiveIntegerField(default=0)),
                ("test_result", models.CharField(choices=[("pending", "Pending"), ("pass", "Pass"), ("fail", "Fail"), ("conditional", "Conditional")], default="pending", max_length=20)),
                ("test_notes", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("trial", "Virtual trial"), ("confirmed", "Trial confirmed"), ("formalized", "Formal product linked"), ("cancelled", "Cancelled")], default="trial", max_length=20)),
                ("trial_confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("formalized_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category_node", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="development_product_archives", to="products.productcategory")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_development_product_archives", to=settings.AUTH_USER_MODEL)),
                ("formal_product", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="development_product_archive", to="products.productspu")),
                ("formalized_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="formalized_development_product_archives", to=settings.AUTH_USER_MODEL)),
                ("project", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="product_archive", to="development.developmentproject")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="development_product_archives", to="tenants.tenant")),
                ("trial_confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_development_product_archives", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="updated_development_product_archives", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["tenant_id", "-created_at"]},
        ),
        migrations.CreateModel(
            name="DevelopmentProductArchiveEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=40)),
                ("from_status", models.CharField(blank=True, max_length=20)),
                ("to_status", models.CharField(blank=True, max_length=20)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="development_product_archive_events", to=settings.AUTH_USER_MODEL)),
                ("archive", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="development.developmentproductarchive")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="development_product_archive_events", to="tenants.tenant")),
            ],
            options={"ordering": ["archive_id", "created_at", "id"]},
        ),
        migrations.AddConstraint(model_name="developmentproductarchive", constraint=models.UniqueConstraint(fields=("tenant", "archive_no"), name="uniq_dev_product_archive_no")),
        migrations.AddIndex(model_name="developmentproductarchive", index=models.Index(fields=["tenant", "status"], name="idx_dev_product_archive_status")),
        migrations.AddIndex(model_name="developmentproductarchive", index=models.Index(fields=["tenant", "platform", "site"], name="idx_dev_product_archive_market")),
        migrations.AddIndex(model_name="developmentproductarchiveevent", index=models.Index(fields=["tenant", "archive", "created_at"], name="idx_dev_product_archive_event")),
    ]
