from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0031_influence_archive_associations")]

    # Both fields use the existing varchar(500); only validation changes.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="influencerprofile",
                    name="profile_url",
                    field=models.CharField(max_length=500, blank=True),
                ),
            ],
        ),
    ]
