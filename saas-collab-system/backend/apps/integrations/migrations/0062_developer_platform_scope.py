from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('integrations', '0061_creator_video_capability_choices')]
    operations = [
        migrations.AddField(
            model_name='developerendpoint',
            name='scope_mode',
            field=models.CharField(choices=[('fixed', 'Fixed'), ('platform', 'Platform')], default='fixed', max_length=16),
        ),
    ]
