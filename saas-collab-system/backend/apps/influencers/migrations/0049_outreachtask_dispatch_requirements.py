from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0048_influencer_username_alias")]
    operations = [
        migrations.AddField(
            model_name="outreachtask",
            name="dispatch_requirements",
            field=models.CharField(blank=True, default="", db_default="", max_length=1000),
        ),
    ]
