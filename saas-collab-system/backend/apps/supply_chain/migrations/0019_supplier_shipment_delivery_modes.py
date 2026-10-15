from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0018_dispatchbatch_carrier_quote_snapshots')]

    operations = [
        migrations.AddField(
            model_name='suppliershipment', name='delivery_mode',
            field=models.CharField(choices=[('collection_center', '送集货中心'), ('factory_loading', '货柜上门装载')],
                                   default='collection_center', max_length=24),
        ),
        migrations.AddField(model_name='suppliershipment', name='loading_address_snapshot',
                            field=models.TextField(blank=True)),
        migrations.AddConstraint(
            model_name='suppliershipment',
            constraint=models.CheckConstraint(condition=~models.Q(delivery_mode='factory_loading') | models.Q(collection_arrived=False),
                                              name='sc2_factory_no_collection_arrival'),
        ),
    ]
