from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0039_fee_item_breakdown')]
    operations = [
        migrations.AddField(model_name='paymentrecord', name='inbound', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payment_records', to='supply_chain.inboundorder')),
        migrations.RemoveConstraint(model_name='paymentrecord', name='sc2_payment_one_owner'),
        migrations.AddConstraint(model_name='paymentrecord', constraint=models.CheckConstraint(condition=(models.Q(purchase_order__isnull=False, shipment__isnull=True, batch__isnull=True, inbound__isnull=True) | models.Q(purchase_order__isnull=True, shipment__isnull=False, batch__isnull=True, inbound__isnull=True) | models.Q(purchase_order__isnull=True, shipment__isnull=True, batch__isnull=False, inbound__isnull=True) | models.Q(purchase_order__isnull=True, shipment__isnull=True, batch__isnull=True, inbound__isnull=False)), name='sc2_payment_one_owner')),
    ]
