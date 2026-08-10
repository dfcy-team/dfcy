from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MiniAppIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "provider",
                    models.CharField(
                        choices=[("wechat", "WeChat")],
                        default="wechat",
                        max_length=20,
                    ),
                ),
                ("subject_digest", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("disabled", "Disabled")],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="miniapp_identities",
                        to="accounts.customuser",
                    ),
                ),
            ],
            options={
                "ordering": ["provider", "user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("provider", "subject_digest"),
                        name="uniq_miniapp_provider_subject",
                    )
                ],
            },
        ),
    ]
