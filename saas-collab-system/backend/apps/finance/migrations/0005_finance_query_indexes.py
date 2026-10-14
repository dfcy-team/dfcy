from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0004_platformfinancetransaction_multiplatform")]
    operations = [
        migrations.AddIndex(model_name="platformfinancetransaction", index=models.Index(fields=["tenant", "-occurred_at_utc", "-id"], name="idx_fin_tx_tenant_time")),
        migrations.AddIndex(model_name="platformfinancetransaction", index=models.Index(fields=["tenant", "business_date"], name="idx_fin_tx_tenant_date")),
    ]
