"""Configuration registration does not opt production into external writes."""
import json
import os
from pathlib import Path
import subprocess
import sys


def read_storage_settings(extra):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("RAW_OSS_", "RAW_LOCAL_", "RAW_PAYLOAD_STORAGE_"))}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings.dev",
                "DB_ENGINE": "django.db.backends.sqlite3", "DB_NAME": ":memory:"})
    env.update(extra)
    result = subprocess.run(
        [sys.executable, "-c", "from django.conf import settings; import json; "
         "print(json.dumps({'alias': settings.RAW_PAYLOAD_STORAGE_ALIAS, 'storages': settings.STORAGES}))"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        text=True, capture_output=True, check=True, timeout=20,
    )
    return json.loads(result.stdout)


def test_default_has_no_external_writes_or_oss_registration():
    result = read_storage_settings({})
    assert result["alias"] == ""
    assert "raw_oss" not in result["storages"]
    assert "raw_local" not in result["storages"]


def test_bucket_registers_backend_without_enabling_writes():
    result = read_storage_settings({
        "RAW_OSS_BUCKET": "test-raw-bucket", "RAW_OSS_REGION": "cn-hangzhou",
        "RAW_OSS_ENDPOINT": "https://oss-cn-hangzhou.aliyuncs.com",
        "RAW_OSS_CREDENTIAL_FILE": "/not-opened/credentials.json",
        "RAW_PAYLOAD_STORAGE_NAMESPACE": "test-env",
    })
    assert result["alias"] == ""
    assert result["storages"]["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
    assert result["storages"]["staticfiles"]["BACKEND"] == "django.contrib.staticfiles.storage.StaticFilesStorage"
    config = result["storages"]["raw_oss"]
    assert config["BACKEND"] == "apps.integrations.raw_oss_storage.PrivateRawOSSStorage"
    assert config["OPTIONS"]["connect_timeout"] == 3
    assert config["OPTIONS"]["read_timeout"] == 10
    assert config["OPTIONS"]["namespace"] == "test-env"


def test_local_registration_does_not_enable_writes():
    result = read_storage_settings({"RAW_LOCAL_ROOT": "/not-created/raw-archive",
                                    "RAW_PAYLOAD_STORAGE_NAMESPACE": "local-test"})
    assert result["alias"] == ""
    assert "raw_oss" not in result["storages"]
    backend = result["storages"]["raw_local"]
    assert backend["BACKEND"] == "apps.integrations.raw_local_storage.PrivateRawLocalStorage"
    assert backend["OPTIONS"]["min_free_bytes"] == 10 * 1024 ** 3


def test_local_and_oss_can_coexist_for_existing_references():
    result = read_storage_settings({"RAW_LOCAL_ROOT": "/not-created/raw-archive",
                                    "RAW_OSS_BUCKET": "offline-test-bucket"})
    assert result["alias"] == ""
    assert {"raw_local", "raw_oss", "default", "staticfiles"} == set(result["storages"])
