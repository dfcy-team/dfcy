import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('supply_chain', '0061_paymentclassification'),
        ('tenants', '0002_department_leader_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='PayableClassificationRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('version', models.PositiveIntegerField(default=1)),
                ('kind', models.CharField(max_length=24)),
                ('currency', models.CharField(max_length=3)),
                ('corporate_amount', models.DecimalField(decimal_places=4, default=0, max_digits=24)),
                ('personal_amount', models.DecimalField(decimal_places=4, default=0, max_digits=24)),
                ('payable_amount', models.DecimalField(decimal_places=4, max_digits=24)),
                ('party_snapshot', models.JSONField(blank=True, default=dict)),
                ('reason', models.TextField(blank=True)),
                ('batch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payable_classifications', to='supply_chain.dispatchbatch')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('shipment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payable_classifications', to='supply_chain.suppliershipment')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.tenant')),
            ],
            options={'constraints': [
                models.CheckConstraint(condition=models.Q(models.Q(('batch__isnull', True), ('shipment__isnull', False)), models.Q(('batch__isnull', False), ('shipment__isnull', True)), _connector='OR'), name='sc2_payclass_one_owner'),
                models.UniqueConstraint(fields=('tenant', 'kind', 'shipment'), name='sc2_payclass_shipment_kind'),
                models.UniqueConstraint(fields=('tenant', 'kind', 'batch'), name='sc2_payclass_batch_kind'),
                models.CheckConstraint(condition=models.Q(('corporate_amount__gte', 0)), name='sc2_payclass_corp_nonnegative'),
                models.CheckConstraint(condition=models.Q(('personal_amount__gte', 0)), name='sc2_payclass_pers_nonnegative'),
                models.CheckConstraint(condition=models.Q(('payable_amount__gte', 0)), name='sc2_payclass_payable_nonnegative'),
            ]},
        ),
    ]
