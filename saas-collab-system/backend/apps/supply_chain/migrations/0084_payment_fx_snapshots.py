"""VM schema only; historical FX compatibility is resolved without rewriting old rows."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0083_wms_document_links')]
    operations = [
        migrations.AddField('supplypaymentrequest', 'exchange_rate', models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True)),
        migrations.AddField('supplypaymentrequest', 'cny_amount', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
        migrations.AddField('supplypaymentbatch', 'exchange_rate', models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True)),
        migrations.AddField('supplypaymentbatch', 'cny_amount', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
        migrations.AddField('paymentrecord', 'exchange_rate', models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True)),
        migrations.AddField('paymentrecord', 'cny_amount', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
    ]
