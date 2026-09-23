from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0024_product_cost_confirmed_interval_exclusion")]

    operations = [
        migrations.AddField(
            model_name="productbundlecomponent",
            name="cost_allocation_ratio",
            field=models.DecimalField(decimal_places=4, default=Decimal("1"), max_digits=10),
        ),
        migrations.AddField(
            model_name="productbundleversioncomponent",
            name="cost_allocation_ratio",
            field=models.DecimalField(decimal_places=4, default=Decimal("1"), max_digits=10),
        ),
        migrations.AddConstraint(
            model_name="productbundlecomponent",
            constraint=models.CheckConstraint(condition=models.Q(cost_allocation_ratio__gt=0), name="bundle_component_ratio_positive"),
        ),
        migrations.AddConstraint(
            model_name="productbundleversioncomponent",
            constraint=models.CheckConstraint(condition=models.Q(cost_allocation_ratio__gt=0), name="bundle_version_component_ratio_positive"),
        ),
    ]
