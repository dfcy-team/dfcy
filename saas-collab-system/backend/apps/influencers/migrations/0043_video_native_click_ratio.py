from decimal import Decimal
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('influencers', '0042_video_reported_ctor')]
    operations = [
        migrations.RemoveConstraint(model_name='tiktokvideodailymetric', name='chk_tk_vmetric_rates'),
        migrations.AlterField(model_name='tiktokvideodailymetric', name='ctr',
            field=models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
        migrations.AddConstraint(model_name='tiktokvideodailymetric',
            constraint=models.CheckConstraint(name='chk_tk_vmetric_rates', condition=(
                models.Q(ctr__gte=0) & models.Q(v_to_l_rate__gte=0, v_to_l_rate__lte=1)
                & models.Q(finish_rate__gte=0, finish_rate__lte=1)
                & models.Q(click_to_order_rate__gte=0, click_to_order_rate__lte=1)))),
    ]
