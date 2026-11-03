from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('masterdata', '0018_archive_code_rule')]

    operations = [
        migrations.CreateModel(
            name='DailyExchangeRateSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rate_date', models.DateField()),
                ('rates', models.JSONField()),
                ('source_url', models.URLField(max_length=500)),
                ('source_hash', models.CharField(max_length=64)),
                ('fetched_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('tenant', 'rate_date'), name='uniq_daily_fx_tenant_date')]},
        ),
    ]
