from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supply_chain', '0017_alter_notificationoutbox_blocked_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='dispatchbatch',
            name='fee_per_cbm_snapshot',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='dispatchbatch',
            name='tax_percent_snapshot',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
