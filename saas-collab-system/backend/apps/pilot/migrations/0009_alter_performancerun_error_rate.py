from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pilot", "0008_pilotexecution_runner_deadline_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="performancerun",
            name="error_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
            ),
        ),
    ]
