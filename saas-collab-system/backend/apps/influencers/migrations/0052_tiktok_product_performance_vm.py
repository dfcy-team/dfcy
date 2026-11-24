from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('influencers', '0051_requirement_images')]
    operations = [migrations.CreateModel(
        name='TikTokProductPerformanceSnapshot',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('product_id', models.CharField(max_length=160)),
            ('window_start', models.DateField()),
            ('window_end', models.DateField()),
            ('metrics', models.JSONField(default=dict)),
            ('source_updated_at', models.DateTimeField(blank=True, null=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.tenant')),
            ('store', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tiktok_product_performance', to='masterdata.storemaster')),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('tenant', 'store', 'product_id', 'window_start', 'window_end'), name='uniq_tk_prod_perf_window')],
                 'indexes': [models.Index(fields=['tenant', 'store', 'product_id', 'window_start'], name='idx_tk_prod_perf_lookup')]},
    )]
