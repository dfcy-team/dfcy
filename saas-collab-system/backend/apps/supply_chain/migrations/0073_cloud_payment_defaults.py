
from django.db import migrations, models
from django.db.models.functions import JSONObject
class Migration(migrations.Migration):
    dependencies = [('supply_chain','0068_merge_inbound_extra_and_payment_plans'),('supply_chain','0072_payee_account_deleted')]
    operations = [
        migrations.AlterField(model_name='supplypaymentrequest',name='currency',field=models.CharField(max_length=3,blank=True,default='',db_default='')),
        migrations.AlterField(model_name='supplypaymentbatch',name='currency',field=models.CharField(max_length=3,blank=True,default='',db_default='')),
        migrations.AlterField(model_name='supplypaymentrequest',name='plan_line_id',field=models.CharField(max_length=64,blank=True,default='',db_default='')),
        migrations.AlterField(model_name='supplypaymentrequest',name='plan_snapshot',field=models.JSONField(blank=True,default=dict,db_default=JSONObject())),
    ]
