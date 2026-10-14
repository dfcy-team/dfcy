"""Disposable local container tests; never select a production endpoint."""
import os
from config.settings.settlement_test import *  # noqa: F401,F403

if os.environ.get("PR304_DISPOSABLE") != "yes":
    raise RuntimeError("Disposable test acknowledgement required")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql", "NAME": "synthetic_pr304",
    "HOST": "127.0.0.1", "PORT": "3306", "USER": "root",
    "PASSWORD": os.environ["MYSQL_ROOT_PASSWORD"],
    "OPTIONS": {"isolation_level": "read committed"},
}}
