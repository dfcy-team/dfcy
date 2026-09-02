from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0013_canonical_tiktok_handle")]

    operations = [
        migrations.AlterField(
            model_name="affiliateordersnapshot",
            name="actual_paid_commission",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AlterField(
            model_name="affiliateordersnapshot",
            name="estimated_paid_commission",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
    ]
