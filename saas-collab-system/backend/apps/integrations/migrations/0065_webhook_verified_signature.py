from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('integrations', '0064_merge_local_best_vm410')]
    operations = [migrations.AlterField(
        model_name='webhookevent', name='signature_status',
        field=models.CharField(max_length=30, choices=[('valid', 'Valid'), ('mock_valid', 'Mock valid'),
                                                      ('invalid', 'Invalid'), ('not_configured', 'Not configured')]),
    )]
