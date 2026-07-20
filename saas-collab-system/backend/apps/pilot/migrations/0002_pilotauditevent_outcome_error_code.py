from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pilot", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="pilotauditevent",
            name="outcome",
            field=models.CharField(
                choices=[("success", "Success"), ("failed", "Failed")],
                default="success",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="pilotauditevent",
            name="error_code",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
