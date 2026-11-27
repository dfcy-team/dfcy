from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies=[('supply_chain','0086_payment_voucher_content_oss')]
    operations=[migrations.AddField(model_name='inboundnotificationconfig',name='arrival_unreceived_reminder_days',field=models.PositiveSmallIntegerField(default=3))]
