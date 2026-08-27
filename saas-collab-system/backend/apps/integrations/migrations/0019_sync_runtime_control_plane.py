import apps.integrations.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _table_names(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        return set(schema_editor.connection.introspection.table_names(cursor))


def _column_names(schema_editor, table_name):
    if table_name not in _table_names(schema_editor):
        return set()
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def _constraint_names(schema_editor, table_name):
    if table_name not in _table_names(schema_editor):
        return set()
    with schema_editor.connection.cursor() as cursor:
        return set(schema_editor.connection.introspection.get_constraints(cursor, table_name))


def ensure_runtime_schema(apps, schema_editor):
    warehouse_authorization = apps.get_model("integrations", "WarehouseAuthorization")
    sync_checkpoint = apps.get_model("integrations", "SyncCheckpoint")
    sync_job = apps.get_model("integrations", "SyncJob")

    if warehouse_authorization._meta.db_table not in _table_names(schema_editor):
        schema_editor.create_model(warehouse_authorization)

    for field_name in ("store_authorization", "sync_scope", "warehouse_authorization"):
        field = sync_job._meta.get_field(field_name)
        sync_job_columns = _column_names(schema_editor, sync_job._meta.db_table)
        if field.column not in sync_job_columns:
            schema_editor.add_field(sync_job, field)

    for constraint in sync_job._meta.constraints:
        if constraint.name not in _constraint_names(schema_editor, sync_job._meta.db_table):
            schema_editor.add_constraint(sync_job, constraint)

    if sync_checkpoint._meta.db_table not in _table_names(schema_editor):
        schema_editor.create_model(sync_checkpoint)


def remove_runtime_schema(apps, schema_editor):
    warehouse_authorization = apps.get_model("integrations", "WarehouseAuthorization")
    sync_checkpoint = apps.get_model("integrations", "SyncCheckpoint")
    sync_job = apps.get_model("integrations", "SyncJob")

    if sync_checkpoint._meta.db_table in _table_names(schema_editor):
        schema_editor.delete_model(sync_checkpoint)
    for constraint in reversed(sync_job._meta.constraints):
        if constraint.name in _constraint_names(schema_editor, sync_job._meta.db_table):
            schema_editor.remove_constraint(sync_job, constraint)
    for field_name in ("warehouse_authorization", "sync_scope", "store_authorization"):
        field = sync_job._meta.get_field(field_name)
        sync_job_columns = _column_names(schema_editor, sync_job._meta.db_table)
        if field.column in sync_job_columns:
            schema_editor.remove_field(sync_job, field)
    if warehouse_authorization._meta.db_table in _table_names(schema_editor):
        schema_editor.delete_model(warehouse_authorization)


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0018_add_lazada_platform_choice"),
        ("masterdata", "0008_merge_country_and_store_branches"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    legacy_state_operations = [
        migrations.AlterField(
            model_name="syncjob",
            name="schedule_type",
            field=models.CharField(choices=[("manual", "Manual"), ("hourly", "Hourly"), ("interval", "Interval"), ("daily", "Daily"), ("weekly", "Weekly"), ("cron", "Cron")], default="manual", max_length=20),
        ),
        migrations.AddField(
            model_name="syncjob",
            name="store_authorization",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sync_jobs", to="integrations.marketplacestoreauthorization"),
        ),
        migrations.AddField(
            model_name="syncjob",
            name="sync_scope",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="WarehouseAuthorization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(max_length=32)),
                ("credential_id", models.CharField(max_length=255)),
                ("token_id", models.CharField(max_length=255)),
                ("credential_mask", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("active", "Active"), ("expired", "Expired"), ("revoked", "Revoked"), ("error", "Error")], default="pending", max_length=32)),
                ("authorized_at", models.DateTimeField(blank=True, null=True)),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=128)),
                ("active_warehouse_binding_key", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_warehouse_authorizations", to=settings.AUTH_USER_MODEL)),
                ("integration_config", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_authorizations", to="integrations.platformintegrationconfig")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="warehouse_authorizations", to="tenants.tenant")),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="updated_warehouse_authorizations", to=settings.AUTH_USER_MODEL)),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="api_authorizations", to="masterdata.warehousemaster")),
            ],
            options={
                "db_table": "integrations_warehouseauthorization",
                "ordering": ["tenant_id", "warehouse_id", "id"],
                "indexes": [models.Index(fields=["tenant", "status"], name="idx_wh_auth_tenant_status"), models.Index(fields=["tenant", "warehouse"], name="idx_wh_auth_tenant_wh")],
            },
        ),
        migrations.AddField(
            model_name="syncjob",
            name="warehouse_authorization",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sync_jobs", to="integrations.warehouseauthorization"),
        ),
        migrations.AddConstraint(
            model_name="syncjob",
            constraint=models.CheckConstraint(condition=models.Q(("store_authorization__isnull", True), _connector="OR", warehouse_authorization__isnull=True), name="chk_sync_job_single_subject"),
        ),
        migrations.AddConstraint(
            model_name="syncjob",
            constraint=models.UniqueConstraint(fields=("tenant", "store_authorization", "resource_type"), name="uniq_sync_job_store_resource"),
        ),
        migrations.AddConstraint(
            model_name="syncjob",
            constraint=models.UniqueConstraint(fields=("tenant", "warehouse_authorization", "resource_type"), name="uniq_sync_job_warehouse_resource"),
        ),
        migrations.CreateModel(
            name="SyncCheckpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cursor_json", models.JSONField(blank=True, default=dict)),
                ("watermark_utc", models.DateTimeField(blank=True, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_success_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="advanced_checkpoints", to="integrations.syncrun")),
                ("sync_job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checkpoints", to="integrations.syncjob")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sync_checkpoints", to="tenants.tenant")),
            ],
            options={
                "indexes": [models.Index(fields=["tenant", "watermark_utc"], name="idx_sync_checkpoint_watermark"), models.Index(fields=["last_success_run"], name="idx_sync_checkpoint_last_run")],
                "constraints": [models.UniqueConstraint(fields=("tenant", "sync_job"), name="uniq_sync_checkpoint_job")],
            },
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(state_operations=legacy_state_operations),
        migrations.RunPython(ensure_runtime_schema, remove_runtime_schema),
        migrations.CreateModel(
            name="SyncRawEnvelope",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("bigseller", "BigSeller"), ("lazada", "Lazada"), ("shopee", "Shopee"), ("tiktok", "TikTok"), ("jifeng_wms", "Jifeng WMS"), ("mock", "Mock"), ("other", "Other")], max_length=30)),
                ("endpoint", models.CharField(max_length=255)),
                ("cursor", models.CharField(blank=True, max_length=255)),
                ("sequence", models.PositiveIntegerField()),
                ("schema_version", models.CharField(default="raw-envelope.v1", max_length=80)),
                ("payload", models.JSONField()),
                ("payload_hash", models.CharField(max_length=64)),
                ("raw_ref", models.CharField(default=apps.integrations.models.raw_envelope_ref, max_length=80, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("store", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sync_raw_envelopes", to="masterdata.storemaster")),
                ("sync_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="raw_envelopes", to="integrations.syncrun")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sync_raw_envelopes", to="tenants.tenant")),
                ("webhook_event", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="raw_envelope", to="integrations.webhookevent")),
            ],
            options={
                "ordering": ["sync_run_id", "sequence"],
                "indexes": [models.Index(fields=["tenant", "platform", "created_at"], name="idx_sync_raw_tenant_time"), models.Index(fields=["payload_hash"], name="idx_sync_raw_payload_hash")],
                "constraints": [
                    models.UniqueConstraint(fields=("sync_run", "sequence"), name="uniq_sync_raw_run_sequence"),
                    models.CheckConstraint(condition=models.Q(models.Q(("sync_run__isnull", False), ("webhook_event__isnull", True)), models.Q(("sync_run__isnull", True), ("webhook_event__isnull", False)), _connector="OR"), name="chk_sync_raw_single_source"),
                ],
            },
        ),
    ]
