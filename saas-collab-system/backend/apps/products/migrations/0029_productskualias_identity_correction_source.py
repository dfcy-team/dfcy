from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0028_legacy_import_spu_group")]

    operations = [
        migrations.AlterField(
            model_name="productskualias",
            name="source",
            field=models.CharField(choices=[("manual", "手动映射"), ("recode", "编码重编"), ("identity_correction", "身份编码更正")], default="manual", max_length=20),
        ),
    ]
