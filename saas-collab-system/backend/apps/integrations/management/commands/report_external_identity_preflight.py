"""Read-only report for store/warehouse external identity migration readiness."""

import hashlib
import json
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _text(value):
    return str(value or "").strip()


def _digest(*values):
    return hashlib.sha256(":".join(_text(value) for value in values).encode("utf-8")).hexdigest()[:12]


def _table_columns(table_name):
    """Return columns that actually exist in the current database schema.

    This command is intentionally usable both immediately before and after
    the external-identity migrations.  The Django model may already contain
    the new fields while the deployed database still has the old schema, so
    callers must not issue an implicit ``SELECT *`` before checking columns.
    """

    with connection.cursor() as cursor:
        if table_name not in connection.introspection.table_names(cursor):
            return set()
        return {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }


def _schema_status(columns, required):
    if not columns:
        return "table_missing"
    return "available" if required <= columns else "legacy"


class Command(BaseCommand):
    help = "Report duplicate or missing store/warehouse external identities without mutating data."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, default=None)

    def handle(self, *args, **options):
        tenant_id = options.get("tenant_id")
        if tenant_id is not None and tenant_id <= 0:
            raise CommandError("--tenant-id must be a positive integer.")

        from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization
        from apps.masterdata.models import StoreMaster, WarehouseMaster

        warnings = []
        store_columns = _table_columns(StoreMaster._meta.db_table)
        platform_model = StoreMaster.platform.field.remote_field.model
        platform_columns = _table_columns(platform_model._meta.db_table)
        store_required = {"id", "tenant_id", "platform_id", "country_code", "external_store_id"}
        store_identity_available = store_required <= store_columns and "platform_type" in platform_columns
        if not store_identity_available:
            warnings.append(
                "store identity columns are not available in the current schema; store duplicate scan was skipped"
            )
            store_rows = ()
        else:
            store_queryset = StoreMaster.objects.all()
            if tenant_id is not None:
                store_queryset = store_queryset.filter(tenant_id=tenant_id)
            # Select only columns that predate the identity-key migration.
            # The model class can be newer than the database during a rolling
            # deployment, so a SELECT * would fail before getattr can help.
            store_rows = store_queryset.values(
                "id",
                "tenant_id",
                "country_code",
                "external_store_id",
                "platform__platform_type",
            ).iterator()

        warehouse_columns = _table_columns(WarehouseAuthorization._meta.db_table)
        config_columns = _table_columns(PlatformIntegrationConfig._meta.db_table)
        warehouse_master_columns = _table_columns(WarehouseMaster._meta.db_table)
        warehouse_required = {"id", "tenant_id", "provider", "status", "warehouse_id"}
        warehouse_legacy_sources = (
            "integration_config_id" in warehouse_columns
            and "platform_config" in config_columns
            and "country_code" in warehouse_master_columns
        )
        warehouse_identity_available = warehouse_required <= warehouse_columns and warehouse_legacy_sources
        if not warehouse_identity_available:
            warnings.append(
                "warehouse identity source columns are not available in the current schema; "
                "warehouse duplicate scan was skipped"
            )

        if warehouse_identity_available:
            authorization_queryset = WarehouseAuthorization.objects.filter(
                status=WarehouseAuthorization.Status.ACTIVE,
            )
            if tenant_id is not None:
                authorization_queryset = authorization_queryset.filter(tenant_id=tenant_id)
            warehouse_fields = [
                "id",
                "tenant_id",
                "provider",
                "warehouse_id",
                "integration_config__platform_config",
                "warehouse__country_code",
            ]
            has_binding_code = "external_warehouse_code" in warehouse_columns
            has_binding_region = "external_warehouse_region" in warehouse_columns
            if has_binding_code:
                warehouse_fields.append("external_warehouse_code")
            if has_binding_region:
                warehouse_fields.append("external_warehouse_region")
            authorization_rows = authorization_queryset.values(*warehouse_fields).iterator()
        else:
            has_binding_code = False
            has_binding_region = False
            authorization_rows = ()

        store_groups = defaultdict(list)
        for row in store_rows:
            external_id = _text(row.get("external_store_id"))
            if not external_id:
                continue
            key = (
                row["tenant_id"],
                _text(row.get("platform__platform_type")).lower(),
                _text(row.get("country_code")).upper(),
                external_id,
            )
            store_groups[key].append(row["id"])
        store_duplicates = [
            {
                "tenant_id": key[0],
                "platform": key[1],
                "region": key[2],
                "identity_digest": _digest(*key),
                "row_ids": ids,
            }
            for key, ids in store_groups.items()
            if len(ids) > 1
        ]

        warehouse_groups = defaultdict(list)
        missing_warehouse_identity = []
        for auth in authorization_rows:
            raw_config = auth.get("integration_config__platform_config")
            config_values = raw_config if isinstance(raw_config, dict) else {}
            code = _text(auth.get("external_warehouse_code")) if has_binding_code else ""
            code = code or _text(config_values.get("warehouse_code"))
            region = (
                (_text(auth.get("external_warehouse_region")) if has_binding_region else "")
                or _text(config_values.get("site_code"))
                or _text(auth.get("warehouse__country_code"))
            ).upper()
            if not code:
                missing_warehouse_identity.append(
                    {
                        "authorization_id": auth["id"],
                        "warehouse_id": auth["warehouse_id"],
                        "provider": auth["provider"],
                        "region": region,
                    }
                )
                continue
            key = (auth["tenant_id"], auth["provider"], region, code)
            warehouse_groups[key].append(auth["id"])
        warehouse_duplicates = [
            {
                "tenant_id": key[0],
                "provider": key[1],
                "region": key[2],
                "identity_digest": _digest(*key),
                "authorization_ids": ids,
            }
            for key, ids in warehouse_groups.items()
            if len(ids) > 1
        ]

        report = {
            "command": "report_external_identity_preflight",
            "tenant_id": tenant_id,
            "counts": {
                "store_duplicate_groups": len(store_duplicates),
                "warehouse_duplicate_groups": len(warehouse_duplicates),
                "warehouse_missing_identity": len(missing_warehouse_identity),
            },
            "store_duplicates": store_duplicates,
            "warehouse_duplicates": warehouse_duplicates,
            "warehouse_missing_identity": missing_warehouse_identity,
            "schema": {
                "store_external_identity": _schema_status(
                    store_columns,
                    {"external_store_id", "external_store_identity_key"},
                ),
                "warehouse_external_identity": _schema_status(
                    warehouse_columns,
                    {"external_warehouse_code", "external_warehouse_region", "external_warehouse_identity_key"},
                ),
            },
            "warnings": warnings,
            "mutated": False,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
