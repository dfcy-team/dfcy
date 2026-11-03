import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('finance', '0009_businesssyncidentity_businesssyncsource_and_more')]

    operations = [migrations.AlterField(
        model_name='warehousefee', name='warehouse',
        field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                to='masterdata.warehousemaster'))]
