from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('commerce', '0012_refundreturnitem_source_details')]
    operations = [migrations.AlterField(
        model_name='salesorder', name='normalized_status',
        field=models.CharField(max_length=40, choices=[
            ('pending', 'Pending'), ('confirmed', 'Confirmed'), ('fulfilled', 'Fulfilled'),
            ('completed', 'Completed'), ('cancellation_pending', 'Cancellation pending'),
            ('cancelled', 'Cancelled')]),
    )]
