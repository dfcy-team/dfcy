#!/usr/bin/env sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
mkdir -p "$tmp_dir/application" "$tmp_dir/database"
cp "$root_dir/application/install-app.sh" "$tmp_dir/application/install-app.sh"
cp "$root_dir/database/install-db.sh" "$tmp_dir/database/install-db.sh"

cat > "$tmp_dir/application/base.env" <<'EOF'
SANDBOX_ENVIRONMENT_CODE=sandbox
SANDBOX_RELEASE_GIT_SHA=0000000000000000000000000000000000000000
SANDBOX_BACKEND_IMAGE=ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:0000000000000000000000000000000000000000000000000000000000000000
SANDBOX_FRONTEND_IMAGE=ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:0000000000000000000000000000000000000000000000000000000000000000
SANDBOX_REDIS_IMAGE=redis@sha256:0000000000000000000000000000000000000000000000000000000000000000
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_SECRET_KEY=sandbox-ci-placeholder-secret-key-value
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=sandbox.test.invalid,backend,localhost
CORS_ALLOWED_ORIGINS=https://sandbox.test.invalid:8543
DB_ENGINE=django.db.backends.mysql
DB_NAME=saas_collab_sandbox
DB_USER=saas_collab_sandbox_user
DB_PASSWORD=sandbox-ci-placeholder-db-password
DB_HOST=192.168.56.12
DB_PORT=3307
REDIS_PASSWORD=sandbox-ci-placeholder-redis-password
INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production
SANDBOX_ALLOW_REAL_PLATFORM=false
SANDBOX_ALLOW_HIGH_RISK_AUTOMATION=false
SANDBOX_PUBLIC_HOST=sandbox.test.invalid
SANDBOX_HTTPS_PORT=8543
SANDBOX_NETWORK_POLICY_FILE=/tmp/sandbox-network.env
SANDBOX_TLS_CERT_PATH=/tmp/sandbox.crt
SANDBOX_TLS_KEY_PATH=/tmp/sandbox.key
SANDBOX_CA_CERT_PATH=/tmp/sandbox-ca.crt
EOF

cat > "$tmp_dir/database/base.env" <<'EOF'
SANDBOX_ENVIRONMENT_CODE=sandbox
SANDBOX_MYSQL_IMAGE=mysql@sha256:0000000000000000000000000000000000000000000000000000000000000000
MYSQL_DATABASE=saas_collab_sandbox
MYSQL_USER=saas_collab_sandbox_user
MYSQL_PASSWORD=sandbox-ci-placeholder-db-password
MYSQL_ROOT_PASSWORD=sandbox-ci-placeholder-root-password
SANDBOX_DB_BIND_IP=192.168.56.12
SANDBOX_DB_PORT=3307
SANDBOX_NETWORK_POLICY_FILE=/tmp/sandbox-network.env
EOF

expect_app_block() {
  field=$1
  value=$2
  expected=$3
  sed "s|^$field=.*|$field=$value|" "$tmp_dir/application/base.env" > "$tmp_dir/application/.env.sandbox"
  if output=$(sh "$tmp_dir/application/install-app.sh" 2>&1); then
    echo "Expected application guard to reject $field." >&2
    exit 1
  fi
  echo "$output" | grep -q "$expected" || { echo "Unexpected guard output for $field: $output" >&2; exit 1; }
}

expect_db_block() {
  field=$1
  value=$2
  expected=$3
  sed "s|^$field=.*|$field=$value|" "$tmp_dir/database/base.env" > "$tmp_dir/database/.env.sandbox"
  if output=$(sh "$tmp_dir/database/install-db.sh" 2>&1); then
    echo "Expected database guard to reject $field." >&2
    exit 1
  fi
  echo "$output" | grep -q "$expected" || { echo "Unexpected guard output for $field: $output" >&2; exit 1; }
}

expect_app_block SANDBOX_BACKEND_IMAGE saas-collab-backend:sandbox "immutable sha256 digest"
expect_app_block DJANGO_SETTINGS_MODULE config.settings.dev "must be config.settings.prod"
expect_app_block DB_ENGINE django.db.backends.sqlite3 "must be django.db.backends.mysql"
expect_app_block SANDBOX_ALLOW_REAL_PLATFORM true "Real platform access is forbidden"
expect_app_block SANDBOX_ALLOW_HIGH_RISK_AUTOMATION true "High-risk automation is forbidden"
expect_app_block DJANGO_ALLOWED_HOSTS 'sandbox.test.invalid,backend,localhost,*' "unapproved host or wildcard"
expect_app_block CORS_ALLOWED_ORIGINS 'https://sandbox.test.invalid:8543,https://other.test.invalid' "must contain only the exact Sandbox HTTPS origin"
expect_db_block SANDBOX_MYSQL_IMAGE mysql:8.4 "immutable sha256 digest"
expect_db_block SANDBOX_DB_BIND_IP 0.0.0.0 "must be a private address"

echo "SANDBOX_INSTALL_GUARDS=PASS"
