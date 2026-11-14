from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0058_merge_local_increment_vm370")]
    operations = [
        migrations.AddField(
            model_name="developerendpoint", name="warehouse_account",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="developer_endpoints", to="integrations.warehouseauthorization"),
        ),
    ]
