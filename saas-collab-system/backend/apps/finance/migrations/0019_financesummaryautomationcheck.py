from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('finance', '0018_alter_warehousebillformatrule_is_active')]
    operations = [migrations.CreateModel(
        name='FinanceSummaryAutomationCheck',
        fields=[
            ('dataset', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to='finance.financesummarydataset')),
            ('checked_at', models.DateTimeField()),
            ('code', models.CharField(max_length=32)),
        ],
    )]
