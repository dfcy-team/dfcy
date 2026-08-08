"""Single-process pilot WSGI entrypoint with request-line logging disabled.

OAuth callback query strings may contain a one-time authorization code and
state.  The pilot runtime therefore must not emit the HTTP request line.
"""

import os
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django

django.setup()

from django.core.wsgi import get_wsgi_application
from django.db import connection
from django.db.migrations.loader import MigrationLoader


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        return


def runtime_metadata():
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        database_version = cursor.fetchone()[0]
    loader = MigrationLoader(connection)
    migration_heads = sorted(f"{app}.{name}" for app, name in loader.graph.leaf_nodes())
    return database_version, migration_heads


def main():
    database_version, migration_heads = runtime_metadata()
    print(f"DATABASE_VERSION={database_version}")
    print("MIGRATION_HEADS=" + ",".join(migration_heads))
    print("BACKEND_READY=http://127.0.0.1:8000")
    print("Access logging is disabled to protect OAuth callback queries.")
    application = get_wsgi_application()
    with make_server("127.0.0.1", 8000, application, handler_class=QuietHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
