from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0012_worker_active")]
    operations = [
        migrations.AddField(model_name="reportexportrequest", name="storage_alias", field=models.CharField(max_length=64, blank=True)),
        migrations.AddField(model_name="reportexportrequest", name="file_size", field=models.PositiveBigIntegerField(null=True, blank=True)),
        migrations.AddField(model_name="reportexportrequest", name="content_type", field=models.CharField(max_length=80, blank=True)),
    ]
