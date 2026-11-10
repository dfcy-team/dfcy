import django.db.models.functions.json
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0063_paymentcurrencyconfirmation')]
    operations = [
        migrations.AddField(model_name='supplypaymentrequest',name='currency',field=models.CharField(max_length=3,blank=True,db_default='',default='')),
        migrations.AddField(model_name='supplypaymentbatch',name='currency',field=models.CharField(max_length=3,blank=True,db_default='',default='')),
    ]
