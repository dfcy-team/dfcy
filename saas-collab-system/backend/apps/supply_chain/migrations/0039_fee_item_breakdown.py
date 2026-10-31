from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0038_payment_item_profiles')]
    operations = [
        migrations.AddField(model_name='feerevision', name='item_breakdown', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='paymentrecord', name='fee_item', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payments', to='supply_chain.paymentitem')),
        migrations.AddField(model_name='paymentrecord', name='item_snapshot', field=models.JSONField(blank=True, default=dict)),
    ]
