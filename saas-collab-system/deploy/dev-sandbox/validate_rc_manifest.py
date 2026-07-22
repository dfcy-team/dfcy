import argparse
import json
import re
from pathlib import Path


DIGEST_RE = re.compile(r"^[a-z0-9./_-]+(?:[:][a-z0-9._-]+)?@sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_env(path):
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env.local")
    args = parser.parse_args()
    env_path = Path(args.env_file).resolve()
    values = parse_env(env_path)

    git_sha = values.get("LOCAL_SANDBOX_APPROVED_GIT_SHA", "")
    if not SHA_RE.fullmatch(git_sha) or set(git_sha) == {"0"}:
        raise SystemExit("Approved Git SHA must be a non-placeholder 40-character SHA.")

    image_keys = (
        "LOCAL_SANDBOX_BACKEND_IMAGE",
        "LOCAL_SANDBOX_FRONTEND_IMAGE",
        "LOCAL_SANDBOX_MYSQL_IMAGE",
        "LOCAL_SANDBOX_REDIS_IMAGE",
    )
    for key in image_keys:
        value = values.get(key, "")
        if not DIGEST_RE.fullmatch(value) or value.endswith("0" * 64):
            raise SystemExit(f"{key} must use a non-placeholder @sha256 digest.")

    manifest_path = (env_path.parent / values.get("LOCAL_SANDBOX_ARTIFACT_MANIFEST", "")).resolve()
    if not manifest_path.is_file():
        raise SystemExit("Approved artifact manifest is missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("environment") != "sandbox" or manifest.get("git_sha") != git_sha:
        raise SystemExit("Artifact manifest environment or Git SHA does not match.")
    manifest_keys = {
        "backend_image": "LOCAL_SANDBOX_BACKEND_IMAGE",
        "frontend_image": "LOCAL_SANDBOX_FRONTEND_IMAGE",
        "mysql_image": "LOCAL_SANDBOX_MYSQL_IMAGE",
        "redis_image": "LOCAL_SANDBOX_REDIS_IMAGE",
    }
    for manifest_key, env_key in manifest_keys.items():
        if manifest.get(manifest_key) != values[env_key]:
            raise SystemExit(f"{env_key} does not match the artifact manifest.")
    print(f"LOCAL_SANDBOX_RC_CONTRACT=PASS git_sha={git_sha}")


if __name__ == "__main__":
    main()
