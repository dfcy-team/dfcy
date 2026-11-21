from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tenants', '0002_department_leader_and_more')]
    operations = [
        migrations.AddField('tenant', 'payment_approval_required', models.BooleanField(default=True)),
        migrations.AddField('tenant', 'payment_approval_version', models.PositiveIntegerField(default=0)),
    ]
