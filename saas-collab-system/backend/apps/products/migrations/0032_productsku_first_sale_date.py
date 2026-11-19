from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("products", "0031_empty_bundle_skus_to_standard")]
    operations = [migrations.AddField(model_name="productsku", name="first_sale_date", field=models.DateField(null=True, blank=True))]
