#!/usr/bin/env sh
set -eu

sandbox_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
project_root=$(CDPATH= cd -- "$sandbox_root/../.." && pwd)
pilot_dir="$project_root/deploy/pilot/application"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
cp "$pilot_dir/install-app.sh" "$tmp_dir/install-app.sh"

if grep -Eq '^[[:space:]]*build:' "$pilot_dir/docker-compose.pilot-app.yml"; then
  echo "Pilot Compose must not build images on the target host." >&2
  exit 1
fi
if grep -Eq 'docker compose .* build' "$pilot_dir/install-app.sh"; then
  echo "Pilot installer must not run a local image build." >&2
  exit 1
fi
grep -q 'image: ${PILOT_BACKEND_IMAGE' "$pilot_dir/docker-compose.pilot-app.yml"
grep -q 'image: ${PILOT_FRONTEND_IMAGE' "$pilot_dir/docker-compose.pilot-app.yml"
grep -q 'verification_status.*pass' "$pilot_dir/install-app.sh"
grep -q 'approved_manifest_sha256' "$pilot_dir/install-app.sh"

cat > "$tmp_dir/.env.pilot" <<'EOF'
PILOT_ENVIRONMENT_CODE=controlled-pilot
PILOT_RELEASE_GIT_SHA=0000000000000000000000000000000000000000
PILOT_ARTIFACT_MANIFEST_FILE=/tmp/sandbox-artifact-manifest.json
PILOT_SANDBOX_EVIDENCE_FILE=/tmp/sandbox-verification-evidence.json
PILOT_BACKEND_IMAGE=ghcr.io/dfcy-team/dfcy/saas-collab-backend:pilot
PILOT_FRONTEND_IMAGE=ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:0000000000000000000000000000000000000000000000000000000000000000
PILOT_REDIS_IMAGE=redis@sha256:0000000000000000000000000000000000000000000000000000000000000000
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=pilot-ci-placeholder-secret-value-long-enough
DJANGO_DEBUG=false
DB_ENGINE=django.db.backends.mysql
INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production
PILOT_TLS_CERT_PATH=/tmp/pilot.crt
PILOT_TLS_KEY_PATH=/tmp/pilot.key
EOF
if output=$(sh "$tmp_dir/install-app.sh" 2>&1); then
  echo "Pilot installer accepted a mutable image tag." >&2
  exit 1
fi
printf '%s' "$output" | grep -q 'immutable sha256 digest' || {
  echo "Unexpected Pilot guard output: $output" >&2
  exit 1
}

echo "PILOT_PROMOTION_GUARDS=PASS"
