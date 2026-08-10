import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReleaseContract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contract_no", models.CharField(max_length=40)),
                ("application_code", models.SlugField(max_length=80)),
                (
                    "environment",
                    models.CharField(
                        choices=[
                            ("development", "Development"),
                            ("test", "Test"),
                            ("preview", "Preview"),
                            ("production", "Production"),
                        ],
                        max_length=20,
                    ),
                ),
                ("commit_sha", models.CharField(max_length=64)),
                ("api_contract_version", models.CharField(max_length=40)),
                ("scope", models.JSONField(default=list)),
                (
                    "risk_level",
                    models.CharField(
                        choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
                        max_length=20,
                    ),
                ),
                ("rollback_version", models.CharField(max_length=120)),
                ("rollback_point", models.CharField(max_length=200)),
                ("stop_conditions", models.JSONField(default=list)),
                ("observation_minutes", models.PositiveIntegerField(default=30)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("review_pending", "Review pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("built", "Built"),
                            ("uploaded", "Uploaded"),
                            ("platform_review", "Platform review"),
                            ("review_failed", "Review failed"),
                            ("scheduled", "Scheduled"),
                            ("releasing", "Releasing"),
                            ("released", "Released"),
                            ("release_failed", "Release failed"),
                            ("observing", "Observing"),
                            ("completed", "Completed"),
                            ("rollback_required", "Rollback required"),
                            ("rolled_back", "Rolled back"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=30,
                    ),
                ),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("idempotency_key_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_contracts_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_contracts",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="ReleaseAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=50)),
                ("from_status", models.CharField(blank=True, max_length=30)),
                ("to_status", models.CharField(blank=True, max_length=30)),
                ("outcome", models.CharField(default="success", max_length=20)),
                ("reason", models.CharField(max_length=500)),
                ("evidence_refs", models.JSONField(blank=True, default=list)),
                ("idempotency_key_hash", models.CharField(max_length=64)),
                ("request_id", models.CharField(max_length=80)),
                ("contract_version", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_audit_events",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "contract",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to="releases.releasecontract",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "base_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="ReleaseArtifact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("build_no", models.CharField(max_length=80)),
                ("commit_sha", models.CharField(max_length=64)),
                ("artifact_hash", models.CharField(max_length=64)),
                ("config_version", models.CharField(max_length=80)),
                ("manifest", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "recorded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_artifacts_recorded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "contract",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifact",
                        to="releases.releasecontract",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ReleaseApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "approval_type",
                    models.CharField(
                        choices=[
                            ("business", "Business"),
                            ("technical", "Technical"),
                            ("security", "Security"),
                            ("rollback", "Rollback"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        choices=[("approved", "Approved"), ("rejected", "Rejected")],
                        max_length=20,
                    ),
                ),
                ("reason", models.CharField(max_length=500)),
                ("decided_at", models.DateTimeField(auto_now_add=True)),
                (
                    "decided_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_approvals_decided",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approvals",
                        to="releases.releasecontract",
                    ),
                ),
            ],
            options={"ordering": ["approval_type", "decided_at"]},
        ),
        migrations.CreateModel(
            name="ReleaseGateResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=80)),
                ("category", models.CharField(max_length=40)),
                (
                    "status",
                    models.CharField(
                        choices=[("passed", "Passed"), ("failed", "Failed")],
                        max_length=20,
                    ),
                ),
                ("evidence_ref", models.CharField(max_length=240)),
                ("evaluated_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="gate_results",
                        to="releases.releasecontract",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="release_gates_recorded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.AddIndex(
            model_name="releasecontract",
            index=models.Index(
                fields=["tenant", "status", "updated_at"],
                name="idx_release_contract_state",
            ),
        ),
        migrations.AddConstraint(
            model_name="releasecontract",
            constraint=models.UniqueConstraint(
                fields=("tenant", "contract_no"),
                name="uniq_release_contract_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="releasecontract",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key_hash"),
                name="uniq_release_contract_create_key",
            ),
        ),
        migrations.AddIndex(
            model_name="releaseauditevent",
            index=models.Index(
                fields=["tenant", "contract", "created_at"],
                name="idx_release_audit_contract",
            ),
        ),
        migrations.AddConstraint(
            model_name="releaseauditevent",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key_hash"),
                name="uniq_release_audit_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="releaseapproval",
            constraint=models.UniqueConstraint(
                fields=("contract", "approval_type"),
                name="uniq_release_approval_type",
            ),
        ),
        migrations.AddConstraint(
            model_name="releasegateresult",
            constraint=models.UniqueConstraint(
                fields=("contract", "code"),
                name="uniq_release_gate_code",
            ),
        ),
    ]
