from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sales_management', '0008_order_warehouse_lookup')]
    operations = [
        migrations.AddField(model_name='orderwarehouselookup', name='next_query_at', field=models.DateTimeField(null=True, db_index=True)),
        migrations.AddField(model_name='orderwarehouselookup', name='retry_count', field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name='orderwarehouselookup', name='followup_required', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='orderwarehouselookup', name='polling_until', field=models.DateTimeField(null=True)),
    ]
