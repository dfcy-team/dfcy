from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("sales_management", "0004_registration_batch_filenames"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="orderregistration", name="deleted_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="orderregistration", name="deleted_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="deleted_order_registrations", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="orderregistration", name="delete_reason", field=models.CharField(blank=True, default="", max_length=500), preserve_default=False),
    ]
