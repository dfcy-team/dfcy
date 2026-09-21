from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0021_seed_bd_performance_config")]
    operations = [
        migrations.AddIndex(
            model_name="affiliateordersnapshot",
            index=models.Index(fields=["tenant", "updated_at"], name="idx_aff_order_updated"),
        ),
    ]
