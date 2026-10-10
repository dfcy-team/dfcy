from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0028_influencer_platform_account")]

    operations = [
        migrations.AddField(
            model_name="influencer", name="canonical_handle_digest",
            field=models.CharField(max_length=64, null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="influencerprofile", name="canonical_external_id_digest",
            field=models.CharField(max_length=64, null=True, blank=True, editable=False),
        ),
        migrations.AddIndex(
            model_name="influencer",
            index=models.Index(fields=["tenant", "canonical_handle_digest"], name="idx_inf_primary_handle"),
        ),
        migrations.AddIndex(
            model_name="influencerprofile",
            index=models.Index(fields=["tenant", "canonical_external_id_digest"], name="idx_inf_primary_external"),
        ),
    ]
