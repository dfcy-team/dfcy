import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0010_warehouse_fee_pending_warehouse'),
        ('integrations', '0007_alter_apiintegrationconfig_options_and_more'),
        ('masterdata', '0018_archive_code_rule'),
        ('tenants', '0002_department_leader_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name='PlatformWalletSync', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('enabled', models.BooleanField(default=False)),
            ('interval_minutes', models.PositiveIntegerField(default=60)),
            ('activated_at', models.DateTimeField(null=True)),
            ('next_run_at', models.DateTimeField(null=True)),
            ('state', models.CharField(default='idle', max_length=24)),
            ('lease', models.UUIDField(null=True)),
            ('running_until', models.DateTimeField(null=True)),
            ('last_run_at', models.DateTimeField(null=True)),
            ('last_error_code', models.CharField(blank=True, max_length=80)),
            ('summary', models.JSONField(default=dict)),
            ('actor', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
        ]),
        migrations.CreateModel(name='PlatformApiWithdrawal', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('source_endpoint', models.CharField(max_length=160)),
            ('external_id', models.CharField(max_length=191)),
            ('transaction_type', models.CharField(max_length=80)),
            ('raw_status', models.CharField(blank=True, max_length=80, null=True)),
            ('currency', models.CharField(max_length=3)),
            ('signed_amount', models.DecimalField(decimal_places=8, max_digits=28)),
            ('original_amount', models.CharField(max_length=80)),
            ('occurred_at_utc', models.DateTimeField()),
            ('observed_at_utc', models.DateTimeField()),
            ('api_fields', models.JSONField(blank=True, default=dict)),
            ('authorization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='integrations.marketplacestoreauthorization')),
            ('store', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='masterdata.storemaster')),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
        ], options={
            'indexes': [models.Index(fields=['tenant', 'store', 'occurred_at_utc'], name='idx_api_withdraw_store_time')],
            'constraints': [models.UniqueConstraint(fields=('tenant', 'store', 'source_endpoint', 'external_id'), name='uniq_api_withdrawal_source')],
        }),
        migrations.CreateModel(name='PlatformWalletCursor', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('watermark', models.DateTimeField(null=True)),
            ('last_attempt_at', models.DateTimeField(null=True)),
            ('last_success_at', models.DateTimeField(null=True)),
            ('last_error_code', models.CharField(blank=True, max_length=80)),
            ('store', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='masterdata.storemaster')),
            ('sync', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='finance.platformwalletsync')),
        ], options={'constraints': [models.UniqueConstraint(fields=('sync', 'store'), name='uniq_wallet_sync_store')]}),
    ]
