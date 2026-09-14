from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0019_outreachtask_owners")]

    operations = [
        migrations.AddIndex(
            model_name="influencer",
            index=models.Index(
                fields=["tenant", "-updated_at", "-id"],
                name="idx_inf_tenant_updated",
            ),
        ),
        migrations.AddIndex(
            model_name="influencer",
            index=models.Index(
                fields=["tenant", "status", "-updated_at"],
                name="idx_inf_tenant_status",
            ),
        ),
        migrations.AddIndex(
            model_name="outreachtask",
            index=models.Index(
                fields=["tenant", "is_deleted", "-created_at", "-id"],
                name="idx_outreach_tenant_list",
            ),
        ),
        migrations.AddIndex(
            model_name="outreachtask",
            index=models.Index(
                fields=["tenant", "status", "is_deleted", "-created_at"],
                name="idx_outreach_tenant_state",
            ),
        ),
        migrations.AddIndex(
            model_name="samplefulfillment",
            index=models.Index(
                fields=["tenant", "is_deleted", "-created_at", "-id"],
                name="idx_sample_tenant_list",
            ),
        ),
        migrations.AddIndex(
            model_name="samplefulfillment",
            index=models.Index(
                fields=["tenant", "status", "is_deleted", "-created_at"],
                name="idx_sample_tenant_state",
            ),
        ),
        migrations.AddIndex(
            model_name="bdsampleattributionsnapshot",
            index=models.Index(
                fields=["tenant", "sampled_at", "owner"],
                name="idx_bd_sample_date_owner",
            ),
        ),
    ]
