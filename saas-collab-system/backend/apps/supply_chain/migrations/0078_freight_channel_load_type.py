from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0077_supplier_deposit_ledger')]
    operations = [
        migrations.AddField(
            model_name='freightchannel',
            name='load_type',
            field=models.CharField(
                max_length=12, choices=[('fcl', '整柜'), ('lcl', '散货')], blank=True, default='',
            ),
        ),
    ]
