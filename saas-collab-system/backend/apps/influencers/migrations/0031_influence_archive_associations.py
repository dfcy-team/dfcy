from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0029_primary_identity_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InfluenceArchiveGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="archive_groups_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="archive_groups_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(version__gte=1), name="chk_inf_archive_version")],
            },
        ),
        migrations.CreateModel(
            name="InfluenceArchiveMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memberships", to="influencers.influencearchivegroup")),
                ("influencer", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="archive_membership", to="influencers.influencer")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="archive_memberships_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["influencer_id"],
                "indexes": [models.Index(fields=["tenant", "group"], name="idx_inf_archive_members")],
            },
        ),
    ]
