from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('finance', '0014_financesummarycalculation'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='WarehouseBillFormatRule',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=100)),
            ('version', models.PositiveIntegerField(default=2)),
            ('config', models.JSONField(default=dict)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
            ('warehouse', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='masterdata.warehousemaster')),
        ], options={'constraints':[models.UniqueConstraint(fields=('tenant','warehouse','name'),name='uniq_wh_bill_format_name')]})]
