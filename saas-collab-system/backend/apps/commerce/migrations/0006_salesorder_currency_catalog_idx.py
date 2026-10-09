from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0005_inventorysnapshot_tenant_recent_idx")]

    operations = [
        migrations.AddIndex(
            model_name="salesorder",
            index=models.Index(fields=["tenant", "currency"], name="idx_sales_order_currency"),
        ),
    ]
