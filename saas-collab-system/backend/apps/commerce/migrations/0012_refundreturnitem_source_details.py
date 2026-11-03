from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('commerce', '0011_salesorder_internal_sync_batch_and_more')]
    operations = [migrations.AddField(model_name='refundreturnitem', name='source_details',
                                     field=models.JSONField(blank=True, default=dict))]
