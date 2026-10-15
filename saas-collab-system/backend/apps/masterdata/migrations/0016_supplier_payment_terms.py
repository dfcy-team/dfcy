from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masterdata", "0015_suppliermaster_city_suppliermaster_factory_address_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="suppliermaster",
            name="first_cooperation_date",
            field=models.DateField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="suppliermaster",
            name="payment_term_days",
            field=models.PositiveSmallIntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="suppliermaster",
            name="payment_term_start",
            field=models.CharField(choices=[("unspecified", "未约定"), ("shipment_date", "供应商发货日"), ("collection_arrival", "集货到仓日"), ("warehouse_arrival", "目的仓到仓日"), ("reconciliation_date", "对账确认日")], default="unspecified", max_length=32),
        ),
        migrations.AddConstraint(
            model_name="suppliermaster",
            constraint=models.CheckConstraint(condition=models.Q(("payment_term_days__isnull", True), models.Q(("payment_term_days__gte", 0), ("payment_term_days__lte", 3650)), _connector="OR"), name="supplier_payment_term_days_range"),
        ),
    ]
