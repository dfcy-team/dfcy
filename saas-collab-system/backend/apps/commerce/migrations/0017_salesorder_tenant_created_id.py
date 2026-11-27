from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0016_summary_item_checkpoint")]
    operations = [
        migrations.AddIndex(
            model_name="salesorder",
            index=models.Index(fields=["tenant", "created_at_utc", "id"], name="idx_sales_tenant_created_id"),
        ),
    ]
