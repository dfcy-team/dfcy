from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0022_merge_local_fx_vm370")]

    operations = [
        migrations.AddField(
            model_name="platformmaster",
            name="warehouse_connector_state",
            field=models.CharField(
                blank=True,
                choices=[("pending", "待确认"), ("selected", "已选择"), ("none", "暂不接入")],
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="platformmaster",
            name="warehouse_connector_key",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="platformmaster",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
