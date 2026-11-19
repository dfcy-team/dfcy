from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('alerts', '0007_remove_inventorydecisionrow_idx_inventory_row_state_and_more')]
    operations = [
        migrations.CreateModel(name='InventoryWarningRun', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('status', models.CharField(choices=[('queued','Queued'),('building','Building'),('ready','Ready'),('partial','Partial'),('failed','Failed')], default='queued', max_length=16)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('completed_at', models.DateTimeField(blank=True, null=True)),
            ('issues', models.JSONField(blank=True, default=list)), ('config', models.JSONField(blank=True, default=dict)),
            ('country', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='masterdata.countrysitemaster')),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.tenant')),
        ], options={'indexes':[models.Index(fields=['tenant','country','status','-created_at'],name='idx_inv_warn_run')]}),
        migrations.CreateModel(name='InventoryWarningRow', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('payload', models.JSONField(blank=True, default=dict)), ('forecast_stockout', models.BooleanField(default=False)),
            ('key_variant_shortage', models.BooleanField(default=False)), ('supply_risk', models.BooleanField(default=False)),
            ('excess_stock', models.BooleanField(default=False)), ('new_product', models.BooleanField(default=False)),
            ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rows', to='alerts.inventorywarningrun')),
            ('sku', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='products.productsku')),
            ('spu', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='products.productspu')),
        ], options={'indexes':[models.Index(fields=['run','spu','sku'],name='idx_inv_warn_spu'),
            models.Index(fields=['run','forecast_stockout','sku'],name='idx_inv_warn_stockout'),
            models.Index(fields=['run','key_variant_shortage','sku'],name='idx_inv_warn_keysku'),
            models.Index(fields=['run','supply_risk','sku'],name='idx_inv_warn_supply'),
            models.Index(fields=['run','excess_stock','sku'],name='idx_inv_warn_excess'),
            models.Index(fields=['run','new_product','sku'],name='idx_inv_warn_new')]}),
        migrations.AddConstraint(model_name='inventorywarningrow', constraint=models.UniqueConstraint(fields=('run','sku'),name='uniq_inv_warn_row')),
    ]
