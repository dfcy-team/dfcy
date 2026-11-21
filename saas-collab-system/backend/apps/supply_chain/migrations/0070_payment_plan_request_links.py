from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0069_paymentrequest_currency')]
    operations = [
        migrations.AddField(model_name='supplypaymentrequest', name='plan',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='payment_requests', to='supply_chain.paymentplanrecord')),
        migrations.AddField(model_name='supplypaymentrequest', name='plan_line_id',
            field=models.CharField(blank=True, default='', max_length=64)),
        migrations.AddField(model_name='supplypaymentrequest', name='plan_snapshot',
            field=models.JSONField(blank=True, default=dict)),
    ]
