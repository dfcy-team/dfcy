from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0005_inventorysnapshot_tenant_recent_idx")]
    operations = [migrations.AddField(
        model_name="salesorder", name="delivered_at_utc",
        field=models.DateTimeField(null=True, blank=True),
    )]
