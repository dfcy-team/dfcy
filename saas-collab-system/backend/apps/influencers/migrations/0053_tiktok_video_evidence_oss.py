from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0052_tiktok_product_performance_vm")]

    operations = [
        migrations.AlterField(model_name="tiktokvideosyncevidence", name="payload", field=models.JSONField(blank=True)),
        migrations.AddField(
            model_name="tiktokvideosyncevidence",
            name="payload_storage_alias",
            field=models.CharField(blank=True, max_length=80, null=True),
        ),
        migrations.AddField(
            model_name="tiktokvideosyncevidence",
            name="payload_object_key",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]
