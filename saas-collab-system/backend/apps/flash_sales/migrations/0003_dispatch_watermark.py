from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("flash_sales", "0002_permissions")]
    operations = [migrations.AddField(model_name="tenantcontrol", name="last_dispatch_at", field=models.DateTimeField(null=True, blank=True))]
