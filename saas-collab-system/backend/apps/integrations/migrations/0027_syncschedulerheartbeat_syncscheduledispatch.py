import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('integrations', '0026_oauth_configuration_digest'), ('tenants', '0001_initial')]
    operations = [
        migrations.CreateModel(name='SyncSchedulerHeartbeat', fields=[
            ('key', models.CharField(max_length=40, primary_key=True, serialize=False)),
            ('last_seen_at', models.DateTimeField()),
        ]),
        migrations.CreateModel(name='SyncScheduleDispatch', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('scheduled_at', models.DateTimeField()),
            ('enqueued_at', models.DateTimeField(blank=True, null=True)),
            ('started_at', models.DateTimeField(blank=True, null=True)),
            ('finished_at', models.DateTimeField(blank=True, null=True)),
            ('status', models.CharField(default='queued', max_length=20)),
            ('reason', models.CharField(blank=True, max_length=240)),
            ('schedule_snapshot', models.JSONField(default=dict)),
            ('sync_job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schedule_dispatches', to='integrations.syncjob')),
            ('sync_run', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='schedule_dispatch', to='integrations.syncrun')),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.tenant')),
        ], options={
            'indexes': [models.Index(fields=['sync_job', 'status'], name='idx_sync_plan_status')],
            'constraints': [models.UniqueConstraint(fields=('sync_job', 'scheduled_at'), name='uniq_sync_plan_occurrence')],
        }),
    ]
