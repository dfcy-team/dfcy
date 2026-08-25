from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0006_sales_details_export")]
    operations = [
        migrations.AlterField(
            model_name="reportexportrequest",
            name="status",
            field=models.CharField(
                choices=[("completed", "Completed"), ("rejected", "Rejected")],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="reportexportrequest",
            name="file_format",
            field=models.CharField(default="csv", max_length=10),
        ),
        migrations.AddField(
            model_name="reportexportrequest",
            name="storage_key",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="reportexportrequest",
            name="file_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="reportexportrequest",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
