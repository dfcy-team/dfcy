from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0070_payment_plan_request_links')]

    operations = [
        migrations.AddField(
            model_name='feerevision',
            name='cost_exchange',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
