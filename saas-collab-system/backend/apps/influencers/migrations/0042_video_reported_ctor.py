import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('influencers', '0041_video_nullable_metrics_and_receipts')]
    operations = [migrations.AddField(
        model_name='tiktokvideodailymetric', name='reported_ctor',
        field=models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True,
            validators=[django.core.validators.MinValueValidator(Decimal('0'))]),
    )]
