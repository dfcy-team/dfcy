from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0073_cloud_payment_defaults')]
    operations = [migrations.AlterField(model_name='inboundorder', name='status', field=models.CharField(max_length=16, choices=[('draft','待核对'),('confirmed','已入库'),('cancelled','已作废')], default='draft'))]
