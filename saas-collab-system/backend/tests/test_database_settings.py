import os
import subprocess
import sys
from pathlib import Path


def run_prod_settings_import(env_overrides, python_code=None):
    env = os.environ.copy()
    env.update(env_overrides)
    for name in (
        "DB_ENGINE",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "INTEGRATION_ENCRYPTION_PROVIDER",
    ):
        if name not in env_overrides:
            env.pop(name, None)

    code = python_code or (
        "import config.settings.prod as prod; "
        "print(prod.DATABASES['default']['ENGINE'])"
    )

    return subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_prod_settings_reject_sqlite():
    result = run_prod_settings_import(
        {
            "DJANGO_SECRET_KEY": "test-secret-key",
            "DJANGO_ALLOWED_HOSTS": "example.test",
            "DB_ENGINE": "django.db.backends.sqlite3",
            "DB_NAME": "db.sqlite3",
            "DB_USER": "unused",
            "DB_PASSWORD": "unused",
            "DB_HOST": "unused",
            "DB_PORT": "0",
        }
    )

    assert result.returncode != 0
    assert "SQLite is not allowed in production" in result.stderr


def test_prod_settings_accept_mysql_from_environment():
    result = run_prod_settings_import(
        {
            "DJANGO_SECRET_KEY": "test-secret-key",
            "DJANGO_ALLOWED_HOSTS": "example.test",
            "DB_ENGINE": "django.db.backends.mysql",
            "DB_NAME": "saas_collab_prod",
            "DB_USER": "saas_collab_user",
            "DB_PASSWORD": "change-me-placeholder",
            "DB_HOST": "mysql",
            "DB_PORT": "3306",
        }
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "django.db.backends.mysql"


def test_prod_mysql_backend_loads_installed_driver():
    result = run_prod_settings_import(
        {
            "DJANGO_SECRET_KEY": "test-secret-key",
            "DJANGO_ALLOWED_HOSTS": "example.test",
            "DB_ENGINE": "django.db.backends.mysql",
            "DB_NAME": "saas_collab_prod",
            "DB_USER": "saas_collab_user",
            "DB_PASSWORD": "change-me-placeholder",
            "DB_HOST": "mysql",
            "DB_PORT": "3306",
        },
        (
            "import django; django.setup(); "
            "from django.db import connection; print(connection.vendor)"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "mysql"


def test_prod_settings_enforce_https_hsts_and_secure_cookies():
    result = run_prod_settings_import(
        {
            "DJANGO_SECRET_KEY": "test-secret-key",
            "DJANGO_ALLOWED_HOSTS": "example.test",
            "DB_ENGINE": "django.db.backends.mysql",
            "DB_NAME": "saas_collab_prod",
            "DB_USER": "saas_collab_user",
            "DB_PASSWORD": "change-me-placeholder",
            "DB_HOST": "mysql",
            "DB_PORT": "3306",
        },
        (
            "import json; import config.settings.prod as prod; "
            "print(json.dumps({"
            "'redirect': prod.SECURE_SSL_REDIRECT, "
            "'session': prod.SESSION_COOKIE_SECURE, "
            "'csrf': prod.CSRF_COOKIE_SECURE, "
            "'hsts': prod.SECURE_HSTS_SECONDS, "
            "'hsts_subdomains': prod.SECURE_HSTS_INCLUDE_SUBDOMAINS, "
            "'hsts_preload': prod.SECURE_HSTS_PRELOAD, "
            "'proxy': prod.SECURE_PROXY_SSL_HEADER"
            "}))"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"redirect": true, "session": true, "csrf": true, "hsts": 31536000, '
        '"hsts_subdomains": true, "hsts_preload": true, '
        '"proxy": ["HTTP_X_FORWARDED_PROTO", "https"]}'
    )
