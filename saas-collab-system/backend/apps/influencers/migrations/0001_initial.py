from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("tenants", "0001_initial")]
    operations = [migrations.CreateModel(name="Influencer", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("code", models.SlugField(max_length=80)), ("name", models.CharField(max_length=120)),
        ("platform", models.CharField(max_length=40)), ("handle", models.CharField(blank=True, max_length=120)),
        ("category", models.CharField(blank=True, max_length=80)), ("follower_count", models.PositiveBigIntegerField(default=0)),
        ("contact_name", models.CharField(blank=True, max_length=80)), ("contact_phone", models.CharField(blank=True, max_length=32)),
        ("contact_email", models.EmailField(blank=True, max_length=254)),
        ("cooperation_status", models.CharField(choices=[("prospect", "Prospect"), ("contacted", "Contacted"), ("cooperating", "Cooperating"), ("paused", "Paused")], default="prospect", max_length=20)),
        ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive")], default="active", max_length=20)),
        ("notes", models.TextField(blank=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="influencers", to="tenants.tenant")),
    ], options={"ordering": ["tenant_id", "code"], "constraints": [models.UniqueConstraint(fields=("tenant", "code"), name="uniq_influencer_code_per_tenant")]})]
