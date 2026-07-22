#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.pilot"
compose_file="$script_dir/docker-compose.pilot-app.yml"

fail() {
  echo "Pilot install blocked: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

valid_digest_image() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9._/:@-]+@sha256:[0-9a-f]{64}$'
}

secure_json_file() {
  file=$1
  label=$2
  case "$file" in /*) ;; *) fail "$label must be an absolute path." ;; esac
  [ -r "$file" ] || fail "$label is missing or unreadable: $file"
  [ ! -L "$file" ] || fail "$label must not be a symbolic link."
  mode=$(stat -c '%a' "$file")
  [ "$mode" = "400" ] || [ "$mode" = "600" ] || fail "$label mode must be 400 or 600."
}

[ -f "$env_file" ] || fail "Missing $env_file. Copy env.pilot.example and inject approved values."
grep -Eq 'change-me|example\.internal|not-a-real' "$env_file" && fail "Placeholder values remain in $env_file."
chmod 600 "$env_file"

[ "$(env_value PILOT_ENVIRONMENT_CODE)" = "controlled-pilot" ] || fail "PILOT_ENVIRONMENT_CODE must be controlled-pilot."
git_sha=$(env_value PILOT_RELEASE_GIT_SHA)
printf '%s' "$git_sha" | grep -Eq '^[0-9a-f]{40}$' || fail "PILOT_RELEASE_GIT_SHA must be a full commit SHA."

backend_image=$(env_value PILOT_BACKEND_IMAGE)
frontend_image=$(env_value PILOT_FRONTEND_IMAGE)
redis_image=$(env_value PILOT_REDIS_IMAGE)
valid_digest_image "$backend_image" || fail "PILOT_BACKEND_IMAGE must use an immutable sha256 digest."
valid_digest_image "$frontend_image" || fail "PILOT_FRONTEND_IMAGE must use an immutable sha256 digest."
valid_digest_image "$redis_image" || fail "PILOT_REDIS_IMAGE must use an immutable sha256 digest."
case "$backend_image" in ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:*) ;; *) fail "Backend image is not from the approved GHCR repository." ;; esac
case "$frontend_image" in ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:*) ;; *) fail "Frontend image is not from the approved GHCR repository." ;; esac
case "$redis_image" in redis@sha256:*|docker.io/library/redis@sha256:*) ;; *) fail "Redis image is not an approved official digest reference." ;; esac
command -v jq >/dev/null 2>&1 || fail "jq is required to verify promotion evidence."
command -v openssl >/dev/null 2>&1 || fail "openssl is required."

artifact_manifest=$(env_value PILOT_ARTIFACT_MANIFEST_FILE)
sandbox_evidence=$(env_value PILOT_SANDBOX_EVIDENCE_FILE)
secure_json_file "$artifact_manifest" "Artifact manifest"
secure_json_file "$sandbox_evidence" "Sandbox verification evidence"
artifact_hash=$(sha256sum "$artifact_manifest" | cut -d' ' -f1)

[ "$(jq -er '.schema_version' "$artifact_manifest")" = "1" ] || fail "Unsupported artifact manifest schema."
[ "$(jq -er '.environment' "$artifact_manifest")" = "sandbox" ] || fail "Artifact manifest must originate from Sandbox artifacts."
[ "$(jq -er '.git_sha' "$artifact_manifest")" = "$git_sha" ] || fail "Pilot Git SHA differs from the artifact manifest."
[ "$(jq -er '.backend_image' "$artifact_manifest")" = "$backend_image" ] || fail "Pilot backend image differs from the artifact manifest."
[ "$(jq -er '.frontend_image' "$artifact_manifest")" = "$frontend_image" ] || fail "Pilot frontend image differs from the artifact manifest."
artifact_migration=$(jq -er '.migration_sha256' "$artifact_manifest")

[ "$(jq -er '.schema_version' "$sandbox_evidence")" = "1" ] || fail "Unsupported Sandbox evidence schema."
[ "$(jq -er '.environment' "$sandbox_evidence")" = "sandbox" ] || fail "Verification evidence is not from Sandbox."
[ "$(jq -er '.verification_status' "$sandbox_evidence")" = "pass" ] || fail "Sandbox verification evidence is not PASS."
[ "$(jq -er '.git_sha' "$sandbox_evidence")" = "$git_sha" ] || fail "Pilot Git SHA was not verified in Sandbox."
[ "$(jq -er '.backend_image' "$sandbox_evidence")" = "$backend_image" ] || fail "Pilot backend digest was not verified in Sandbox."
[ "$(jq -er '.frontend_image' "$sandbox_evidence")" = "$frontend_image" ] || fail "Pilot frontend digest was not verified in Sandbox."
[ "$(jq -er '.redis_image' "$sandbox_evidence")" = "$redis_image" ] || fail "Pilot Redis digest was not verified in Sandbox."
[ "$(jq -er '.migration_sha256' "$sandbox_evidence")" = "$artifact_migration" ] || fail "Sandbox migration evidence differs from the artifact manifest."
[ "$(jq -er '.approved_manifest_sha256' "$sandbox_evidence")" = "$artifact_hash" ] || fail "Sandbox evidence does not reference the supplied artifact manifest."
jq -e '.network_evidence_sha256 | length == 5 and all(.[]; test("^[0-9a-f]{64}$"))' "$sandbox_evidence" >/dev/null || fail "Sandbox PASS evidence does not contain all approved network evidence hashes."

[ "$(env_value DJANGO_SETTINGS_MODULE)" = "config.settings.prod" ] || fail "DJANGO_SETTINGS_MODULE must be config.settings.prod."
[ "$(env_value DJANGO_DEBUG)" = "false" ] || fail "DJANGO_DEBUG must be false."
[ "$(env_value DB_ENGINE)" = "django.db.backends.mysql" ] || fail "DB_ENGINE must be django.db.backends.mysql."
[ "$(env_value INTEGRATION_ENCRYPTION_PROVIDER)" = "unconfigured-production" ] || fail "Real integration credential storage must remain disabled."

tls_cert_path=$(env_value PILOT_TLS_CERT_PATH)
tls_key_path=$(env_value PILOT_TLS_KEY_PATH)
case "$tls_cert_path:$tls_key_path" in /*:/*) ;; *) fail "Pilot TLS certificate and key paths must be absolute." ;; esac
[ -r "$tls_cert_path" ] && grep -q "BEGIN CERTIFICATE" "$tls_cert_path" || fail "Invalid Pilot TLS certificate."
[ -r "$tls_key_path" ] && grep -Eq "BEGIN (RSA |EC )?PRIVATE KEY" "$tls_key_path" || fail "Invalid Pilot TLS private key."
openssl x509 -checkend 86400 -noout -in "$tls_cert_path" >/dev/null || fail "Pilot TLS certificate expires within 24 hours."
cert_key=$(openssl x509 -in "$tls_cert_path" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256)
private_key=$(openssl pkey -in "$tls_key_path" -pubout 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256)
[ -n "$cert_key" ] && [ "$cert_key" = "$private_key" ] || fail "Pilot TLS certificate and private key do not match."

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" pull redis backend frontend
backend_revision=$(docker image inspect "$backend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
frontend_revision=$(docker image inspect "$frontend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[ "$backend_revision" = "$git_sha" ] || fail "Backend OCI revision differs from the approved Git SHA."
[ "$frontend_revision" = "$git_sha" ] || fail "Frontend OCI revision differs from the approved Git SHA."

docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180 redis
docker compose --env-file "$env_file" -f "$compose_file" run --rm migrate
docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180 backend celery celery-beat frontend

runtime_migration=$(docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python - <<'PY'
from hashlib import sha256
from pathlib import Path

digest = sha256()
for path in sorted(Path("/app/apps").glob("*/migrations/*.py")):
    digest.update(str(path.relative_to("/app")).encode())
    digest.update(path.read_bytes())
print(digest.hexdigest())
PY
)
[ "$runtime_migration" = "$artifact_migration" ] || fail "Pilot runtime migration digest differs from Sandbox evidence."
docker compose --env-file "$env_file" -f "$compose_file" ps
echo "PILOT_SAME_DIGEST_PROMOTION=PASS git_sha=$git_sha"
