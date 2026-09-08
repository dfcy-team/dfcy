from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0015_samplefulfillment_direct_link_type")]

    operations = [
        migrations.AddField(
            model_name="fulfillmentstatusevent",
            name="source",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=40,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="fulfillmentstatusevent",
            name="source_event_id",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=160,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="fulfillmentstatusevent",
            name="source_status",
            field=models.CharField(
                blank=True,
                default=None,
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="fulfillmentstatusevent",
            constraint=models.UniqueConstraint(
                fields=("tenant", "source", "source_event_id"),
                name="uniq_fulfillment_status_source_event",
            ),
        ),
    ]
