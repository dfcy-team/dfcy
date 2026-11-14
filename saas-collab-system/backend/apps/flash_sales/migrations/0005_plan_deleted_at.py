from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("flash_sales", "0004_slot_reservation_history")]
    operations = [migrations.AddField(model_name="plan", name="deleted_at",
                                    field=models.DateTimeField(blank=True, null=True))]
