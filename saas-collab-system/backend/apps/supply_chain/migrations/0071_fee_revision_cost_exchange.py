from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0068_merge_inbound_extra_and_payment_plans')]

    operations = [
        migrations.AddField(
            model_name='feerevision',
            name='cost_exchange',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
