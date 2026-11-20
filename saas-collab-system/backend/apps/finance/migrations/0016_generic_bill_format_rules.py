from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('finance', '0015_warehouse_bill_format_rule')]
    operations = [migrations.AlterField(model_name='warehousebillformatrule', name='warehouse', field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, to='masterdata.warehousemaster'))]
