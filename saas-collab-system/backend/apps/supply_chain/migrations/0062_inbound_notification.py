from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('supply_chain', '0061_payment_request_attachments')]
    operations = [
        migrations.CreateModel(name='InboundNotificationConfig', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('chat_id', models.CharField(blank=True, max_length=191)), ('chat_name', models.CharField(blank=True, max_length=191)),
            ('country_codes', models.JSONField(default=list)), ('enabled', models.BooleanField(default=False)),
            ('all_countries', models.BooleanField(default=False)),
            ('version', models.PositiveIntegerField(default=1)), ('updated_at', models.DateTimeField(auto_now=True)),
            ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='accounts.customuser')),
            ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='inbound_notification_config', to='tenants.tenant')),
        ]),
        migrations.CreateModel(name='InboundNotificationOutbox', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('event_key', models.CharField(max_length=64, unique=True)), ('chat_id', models.CharField(max_length=191)),
            ('chat_name', models.CharField(blank=True, max_length=191)), ('country_code', models.CharField(max_length=8)),
            ('payload', models.JSONField(default=dict)),
            ('app_id', models.CharField(max_length=191, blank=True)),
            ('app_domain', models.CharField(max_length=20, blank=True)),
            ('status', models.CharField(choices=[('pending','Pending'),('sent','Sent'),('failed','Failed'),('needs_review','Needs review'),('skipped','Skipped')], default='pending', max_length=24)),
            ('attempts', models.PositiveSmallIntegerField(default=0)), ('next_attempt_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('lease_until', models.DateTimeField(blank=True, null=True)),
            ('receipt_id', models.CharField(blank=True, max_length=191)), ('error_code', models.CharField(blank=True, max_length=80)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('sent_at', models.DateTimeField(blank=True, null=True)),
            ('inbound', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='supply_chain.inboundorder')),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.tenant')),
        ], options={'constraints':[models.UniqueConstraint(fields=('tenant','inbound'), name='sc2_inbound_notify_once')]}),
    ]
