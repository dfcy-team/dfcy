import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("packing", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PackingApiIdempotencyRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("scope_key", models.CharField(max_length=255)),
                ("idempotency_key", models.CharField(max_length=128)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("internal", "Internal"),
                            ("supplier_web", "Supplier web"),
                            ("miniapp", "Mini Program"),
                        ],
                        max_length=20,
                    ),
                ),
                ("action", models.CharField(max_length=40)),
                ("resource_key", models.CharField(max_length=255)),
                ("request_hash", models.CharField(max_length=64)),
                ("http_status", models.PositiveSmallIntegerField()),
                (
                    "response_kind",
                    models.CharField(
                        choices=[("json", "JSON"), ("label", "Label")],
                        max_length=10,
                    ),
                ),
                ("response_body", models.JSONField(blank=True, null=True)),
                ("label_snapshot", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="packing_api_idempotency_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="packing_api_idempotency_records",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "ordering": ["tenant_id", "-created_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["tenant", "idempotency_key"],
                        name="idx_pack_api_tenant_key",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "scope_key", "idempotency_key"),
                        name="uniq_pack_api_scope_key",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("http_status__gte", 200),
                            ("http_status__lt", 300),
                        ),
                        name="pack_api_http_success",
                    ),
                ],
            },
        ),
    ]
