from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0037_bd_exchange_rates_direct_save")]
    operations = [
        migrations.AddField(
            model_name="affiliateordersnapshot", name="business_identity_digest",
            field=models.CharField(max_length=64, null=True, blank=True, editable=False),
        ),
        migrations.AddIndex(
            model_name="affiliateordersnapshot",
            index=models.Index(fields=["tenant", "business_identity_digest"], name="idx_aff_order_identity"),
        ),
    ]
