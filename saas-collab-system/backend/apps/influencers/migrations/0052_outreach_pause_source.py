from django.db import migrations, models


class Migration(migrations.Migration):
    # The production overlay follows 0051_tiktok_product_performance instead.
    dependencies = [("influencers", "0050_outreach_paused_choice")]
    operations = [
        migrations.AddField(
            model_name="outreachtask",
            name="paused_from_pending",
            field=models.BooleanField(default=False, db_default=False, editable=False),
        ),
    ]
