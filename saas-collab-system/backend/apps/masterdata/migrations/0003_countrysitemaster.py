from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0002_alter_suppliermaster_status")]

    operations = [
        migrations.CreateModel(
            name="CountrySiteMaster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=80)),
                ("name", models.CharField(max_length=120)),
                ("country_code", models.CharField(max_length=8)),
                ("platform", models.CharField(max_length=60)),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive")], default="active", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="country_site_masters", to="tenants.tenant")),
            ],
            options={"ordering": ["tenant_id", "code"]},
        ),
        migrations.AddConstraint(
            model_name="countrysitemaster",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_country_site_master_code"),
        ),
    ]
