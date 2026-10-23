"""Read-only deployment preflight for the isolated demo sync service role."""
import json
import os
import stat
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.demo_sync.service import ReadonlyClient, SyncFailure


DATABASE_PREFIX = "saas_collab_sync_"


class PreflightFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _artifact_directory():
    configured = getattr(settings, "DEMO_DATA_SYNC_ARTIFACT_ROOT", "")
    if not configured:
        raise PreflightFailure("ARTIFACT_ROOT_NOT_CONFIGURED")
    path = Path(configured)
    if not path.is_absolute():
        raise PreflightFailure("ARTIFACT_ROOT_NOT_ABSOLUTE")
    # Resolve only after rejecting symlinks, so a configured link is never silently
    # accepted as a private artifact location.
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise PreflightFailure("ARTIFACT_ROOT_SYMLINK_REJECTED")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise PreflightFailure("ARTIFACT_ROOT_MISSING") from None
    if not resolved.is_dir():
        raise PreflightFailure("ARTIFACT_ROOT_NOT_DIRECTORY")
    media_root = Path(getattr(settings, "MEDIA_ROOT", "")).resolve()
    if resolved == media_root or media_root in resolved.parents:
        raise PreflightFailure("ARTIFACT_ROOT_INSIDE_MEDIA")
    static_root = getattr(settings, "STATIC_ROOT", "")
    if static_root:
        static_path = Path(static_root).resolve()
        if resolved == static_path or static_path in resolved.parents:
            raise PreflightFailure("ARTIFACT_ROOT_INSIDE_STATIC")
    if os.name == "posix":
        try:
            mode = stat.S_IMODE(resolved.stat().st_mode)
        except OSError:
            raise PreflightFailure("ARTIFACT_PERMISSIONS_UNREADABLE") from None
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PreflightFailure("ARTIFACT_PERMISSIONS_TOO_OPEN")
    else:
        # Python's portable stat mode does not prove Windows ACL privacy.
        raise PreflightFailure("ARTIFACT_ACL_REQUIRES_OPERATOR_VALIDATION")
    return resolved


def _configured_sources():
    sources = getattr(settings, "DEMO_DATA_SYNC_SOURCES", None)
    if not isinstance(sources, dict) or not sources:
        raise PreflightFailure("SOURCE_CONFIG_MISSING")
    checked = []
    for alias, source in sources.items():
        if not isinstance(source, dict):
            raise PreflightFailure("SOURCE_CONFIG_INVALID")
        tenant_id = source.get("tenant_id")
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id <= 0:
            raise PreflightFailure("SOURCE_TENANT_INVALID")
        checked.append((alias, source, tenant_id))
    return checked


class Command(BaseCommand):
    help = "Verify the isolated demo sync service role without starting sync work."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-disabled", action="store_true",
            help="Prepare-check the service while sync or worker flags are disabled.",
        )

    def handle(self, *args, **options):
        checks = {}
        failures = []

        def record(name, operation):
            try:
                result = operation()
                checks[name] = "ok"
                return result
            except PreflightFailure as error:
                checks[name] = "failed"
                failures.append(error.code)
            except SyncFailure as error:
                checks[name] = "failed"
                failures.append(error.code)
            except Exception:
                # Do not expose arbitrary exception text, which may include URLs,
                # credentials, SQL values, or database connection details.
                checks[name] = "failed"
                failures.append("PREFLIGHT_CHECK_FAILED")
                return None

        # This must precede every operation that can touch the database.
        if not getattr(settings, "DEMO_DATA_SYNC_SERVICE_INSTANCE", False):
            checks["service_role"] = "failed"
            failures.append("INTRANET_SERVICE_ROLE_REQUIRED")
            return self._finish(checks, failures)
        checks["service_role"] = "ok"

        if not options["allow_disabled"]:
            if (not getattr(settings, "DEMO_DATA_SYNC_ENABLED", False)
                    or not getattr(settings, "DEMO_DATA_SYNC_WORKER_ENABLED", False)):
                checks["feature_flags"] = "failed"
                failures.append("WORKER_DISABLED")
            else:
                checks["feature_flags"] = "ok"
        else:
            checks["feature_flags"] = "prepare_only"
        if getattr(settings, "DEMO_DATA_SYNC_IMPORT_ENABLED", False):
            checks["import_disabled"] = "failed"
            failures.append("IMPORT_MUST_REMAIN_DISABLED")
        else:
            checks["import_disabled"] = "ok"
        if failures:
            return self._finish(checks, failures)

        sources = record("sources", _configured_sources)
        artifact_root = record("artifact_root", _artifact_directory)
        # Don't enter DB checks if an earlier non-DB deployment prerequisite failed.
        if failures:
            return self._finish(checks, failures)

        record("database_vendor", self._check_database_vendor)
        if failures:
            return self._finish(checks, failures)
        record("database_name", self._check_database_name)
        if failures:
            return self._finish(checks, failures)
        record("pending_migrations", self._check_migrations)
        if failures:
            return self._finish(checks, failures)
        record("source_tenants", lambda: self._check_tenants(sources))
        if failures:
            return self._finish(checks, failures)
        record("source_client", lambda: self._check_source_clients(sources))
        return self._finish(checks, failures)

    def _check_database_vendor(self):
        if connection.vendor != "mysql":
            raise PreflightFailure("DATABASE_VENDOR_NOT_MYSQL")
        return "ok"

    def _check_database_name(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            row = cursor.fetchone()
        name = row[0] if row else None
        if not isinstance(name, str) or not name.startswith(DATABASE_PREFIX):
            raise PreflightFailure("DATABASE_NAME_NOT_ISOLATED")
        return "ok"

    def _check_migrations(self):
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            raise PreflightFailure("MIGRATIONS_PENDING")
        return "ok"

    def _check_tenants(self, sources):
        tenant_model = apps.get_model("tenants", "Tenant")
        table = connection.ops.quote_name(tenant_model._meta.db_table)
        column = connection.ops.quote_name(tenant_model._meta.pk.column)
        with connection.cursor() as cursor:
            for _alias, _source, tenant_id in sources:
                cursor.execute(f"SELECT {column} FROM {table} WHERE {column} = %s", [tenant_id])
                if cursor.fetchone() is None:
                    raise PreflightFailure("SOURCE_TENANT_NOT_FOUND")
        return "ok"

    @staticmethod
    def _check_source_clients(sources):
        clients = []
        try:
            for _alias, source, _tenant_id in sources:
                clients.append(ReadonlyClient(source))
        finally:
            for client in clients:
                client.close()
        return "ok"

    def _finish(self, checks, failures):
        result = {"ok": not failures, "checks": checks, "failures": failures}
        self.stdout.write(json.dumps(result, sort_keys=True))
        if failures:
            raise CommandError(failures[0])
        return None
