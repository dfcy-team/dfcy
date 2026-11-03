from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales_management", "0003_registration_permissions")]
    operations = [
        migrations.AddField(model_name="registrationimportbatch", name="file_name", field=models.CharField(blank=True, default="", max_length=255), preserve_default=False),
        migrations.AddField(model_name="registrationimportbatch", name="attachment_name", field=models.CharField(blank=True, default="", max_length=255), preserve_default=False),
        migrations.RemoveConstraint(model_name="registrationimportbatch", name="uniq_registration_batch"),
        migrations.AddConstraint(model_name="registrationimportbatch", constraint=models.UniqueConstraint(fields=("tenant", "kind", "file_hash", "imported_by"), name="uniq_registration_batch")),
    ]
