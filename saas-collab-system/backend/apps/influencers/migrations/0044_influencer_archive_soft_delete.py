from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('influencers', '0043_video_native_click_ratio')]
    operations = [
        migrations.AddField(model_name='influencer', name='is_deleted', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='influencer', name='deleted_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='influencer', name='deletion_previous_status', field=models.CharField(max_length=20, blank=True)),
        migrations.AddConstraint(model_name='influencer', constraint=models.CheckConstraint(condition=models.Q(is_deleted=False) | models.Q(status='inactive'), name='chk_inf_deleted_inactive')),
        migrations.AddConstraint(model_name='influencer', constraint=models.CheckConstraint(condition=models.Q(is_deleted=True, deleted_at__isnull=False) | models.Q(is_deleted=False, deleted_at__isnull=True), name='chk_inf_deleted_timestamp')),
    ]
