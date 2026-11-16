import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0044_outreach_paused_choice")]

    operations = [
        migrations.CreateModel(
            name="InfluencerUsernameAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("influencer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="username_aliases", to="influencers.influencer")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
            ],
            options={"constraints": [models.UniqueConstraint(
                fields=("tenant", "influencer", "username"), name="uniq_inf_username_alias",
            )]},
        ),
    ]
