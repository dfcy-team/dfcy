from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("influencers", "0038_affiliate_business_identity")]

    operations = [
        migrations.AddField(
            model_name="samplefulfillment", name="type_no",
            field=models.CharField(blank=True, default=None, max_length=80, null=True),
        ),
        migrations.AddConstraint(
            model_name="samplefulfillment",
            constraint=models.UniqueConstraint(fields=("tenant", "type_no"), name="uniq_sample_type_no"),
        ),
        migrations.CreateModel(
            name="InfluencerNumberReservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("namespace", models.CharField(choices=[("task", "Task"), ("sample", "Sample"), ("type", "Sample type")], max_length=12)),
                ("number", models.CharField(max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
                ("task", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="number_reservations", to="influencers.outreachtask")),
                ("sample", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="number_reservations", to="influencers.samplefulfillment")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "namespace", "number"), name="uniq_inf_business_number"),
                    models.CheckConstraint(
                        condition=(models.Q(namespace="task", task__isnull=False, sample__isnull=True)
                                   | models.Q(namespace__in=["sample", "type"], task__isnull=True, sample__isnull=False)),
                        name="chk_inf_number_owner",
                    ),
                ],
            },
        ),
    ]
