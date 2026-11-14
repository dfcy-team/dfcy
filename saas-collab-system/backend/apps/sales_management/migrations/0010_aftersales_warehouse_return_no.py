from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sales_management', '0009_order_warehouse_schedule')]
    operations = [migrations.AddField(
        model_name='aftersalescase', name='warehouse_return_no',
        field=models.CharField(max_length=191, blank=True),
    )]
