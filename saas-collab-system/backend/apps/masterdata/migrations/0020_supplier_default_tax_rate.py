from django.db import migrations, models


def copy_maintained_rates(apps, schema_editor):
    Supplier = apps.get_model('masterdata', 'SupplierMaster')
    # Legacy zero was also the default; only carry forward positively maintained rates.
    Supplier.objects.using(schema_editor.connection.alias).filter(tax_percent__gt=0).update(default_tax_rate=models.F('tax_percent'))


class Migration(migrations.Migration):

    dependencies = [
        ('masterdata', '0019_suppliermaster_payment_reminder_days_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='suppliermaster',
            name='default_tax_rate',
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True, default=None),
        ),
        migrations.RunPython(copy_maintained_rates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='suppliermaster',
            constraint=models.CheckConstraint(
                condition=models.Q(('default_tax_rate__isnull', True)) | models.Q(('default_tax_rate__gte', 0), ('default_tax_rate__lte', 100)),
                name='supplier_default_tax_rate_range',
            ),
        ),
    ]
