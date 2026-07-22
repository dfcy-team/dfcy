import json
import tempfile
from pathlib import Path

from validate_fixtures import FIXTURE_DIR, MODULE_FILES, validate_fixture
from validate_rc_manifest import validate_env_file


ROOT = Path(__file__).resolve().parent
DIGEST = "1" * 64
GIT_SHA = "2" * 40


def expect_rejected(env_path, message):
    try:
        validate_env_file(env_path)
    except SystemExit:
        return
    raise AssertionError(message)


def validate_fixture_contract():
    fixture_names = {name for names in MODULE_FILES.values() for name in names}
    for filename in sorted(fixture_names):
        validate_fixture(FIXTURE_DIR / filename)


def validate_local_safety_defaults():
    values = {}
    for raw_line in (ROOT / "env.local.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    expected = {
        "LOCAL_SANDBOX_ENVIRONMENT": "local-sandbox",
        "SANDBOX_ALLOW_REAL_PLATFORM": "false",
        "SANDBOX_ALLOW_HIGH_RISK_AUTOMATION": "false",
        "INTEGRATION_ENCRYPTION_PROVIDER": "test-only",
    }
    for key, value in expected.items():
        if values.get(key) != value:
            raise AssertionError(f"Unsafe Local Sandbox default: {key}")


def validate_rc_positive_and_negative_contracts():
    images = {
        "backend_image": f"ghcr.io/example/project/backend@sha256:{DIGEST}",
        "frontend_image": f"ghcr.io/example/project/frontend@sha256:{DIGEST}",
        "mysql_image": f"mysql@sha256:{DIGEST}",
        "redis_image": f"redis@sha256:{DIGEST}",
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(
            json.dumps({"environment": "sandbox", "git_sha": GIT_SHA, **images}),
            encoding="utf-8",
        )
        env_path = directory / ".env.contract"
        env_path.write_text(
            "\n".join(
                (
                    f"LOCAL_SANDBOX_APPROVED_GIT_SHA={GIT_SHA}",
                    f"LOCAL_SANDBOX_BACKEND_IMAGE={images['backend_image']}",
                    f"LOCAL_SANDBOX_FRONTEND_IMAGE={images['frontend_image']}",
                    f"LOCAL_SANDBOX_MYSQL_IMAGE={images['mysql_image']}",
                    f"LOCAL_SANDBOX_REDIS_IMAGE={images['redis_image']}",
                    "LOCAL_SANDBOX_ARTIFACT_MANIFEST=manifest.json",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        if validate_env_file(env_path) != GIT_SHA:
            raise AssertionError("Valid release-candidate manifest was not accepted.")

        placeholder_env = directory / ".env.placeholder"
        placeholder_env.write_text(
            env_path.read_text(encoding="utf-8").replace(GIT_SHA, "0" * 40),
            encoding="utf-8",
        )
        expect_rejected(placeholder_env, "Placeholder Git SHA was accepted.")

        mismatched_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mismatched_manifest["backend_image"] = f"ghcr.io/example/project/other@sha256:{DIGEST}"
        manifest_path.write_text(json.dumps(mismatched_manifest), encoding="utf-8")
        expect_rejected(env_path, "Mismatched image digest was accepted.")


def main():
    validate_fixture_contract()
    validate_local_safety_defaults()
    validate_rc_positive_and_negative_contracts()
    print("LOCAL_SANDBOX_CONTRACT=PASS fixtures=all rc=positive-and-negative safety=locked")


if __name__ == "__main__":
    main()
