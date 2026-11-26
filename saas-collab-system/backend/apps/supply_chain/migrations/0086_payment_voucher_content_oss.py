from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0085_receipt_difference_decisions")]
    operations = [
        migrations.AlterField(model_name="paymentvoucher", name="content",
                              field=models.BinaryField(blank=True)),
        migrations.AddField(model_name="paymentvoucher", name="content_storage_alias",
                            field=models.CharField(max_length=80, null=True, blank=True)),
        migrations.AddField(model_name="paymentvoucher", name="content_object_key",
                            field=models.CharField(max_length=500, null=True, blank=True)),
    ]

