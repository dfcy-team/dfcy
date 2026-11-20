from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('finance', '0016_generic_bill_format_rules')]
    operations = [migrations.AddField(model_name='warehousebillformatrule', name='is_active', field=models.BooleanField(default=True))]
