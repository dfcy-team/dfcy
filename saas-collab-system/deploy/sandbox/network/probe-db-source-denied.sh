#!/usr/bin/env sh
set -eu

policy_file=${1:-/etc/saas-collab/sandbox-network.env}
evidence_file=${2:-}

fail() {
  echo "Sandbox unapproved database source probe failed: $*" >&2
  exit 1
}

value() {
  sed -n "s/^$1=//p" "$policy_file" | tail -n 1 | tr -d '\r'
}

[ -r "$policy_file" ] || fail "Policy file is missing."
[ "$(value SANDBOX_UNAPPROVED_SOURCE_PROBE)" = "YES" ] || fail "Explicit probe approval is required on the independent source host."
command -v nc >/dev/null 2>&1 || fail "netcat is required."
command -v ip >/dev/null 2>&1 || fail "iproute2 is required."

db_ip=$(value SANDBOX_DB_HOST_IP)
db_port=$(value SANDBOX_DB_PORT)
approved_app_ip=$(value SANDBOX_APP_HOST_IP)
source_ip=$(ip route get "$db_ip" | sed -n 's/.* src \([^ ]*\).*/\1/p' | head -n 1)
[ -n "$source_ip" ] || fail "Cannot determine the probe source IP."
[ "$source_ip" != "$approved_app_ip" ] || fail "This host is the approved application source; use an independent unapproved host."
if nc -z -w 5 "$db_ip" "$db_port" >/dev/null 2>&1; then
  fail "Database connection unexpectedly succeeded from unapproved source $source_ip."
fi

[ -n "$evidence_file" ] || evidence_file="$(value SANDBOX_NETWORK_STATE_DIR)/unapproved-db-source-evidence.json"
case "$evidence_file" in /*) ;; *) fail "Evidence path must be absolute." ;; esac
evidence_dir=$(dirname "$evidence_file")
[ -d "$evidence_dir" ] && [ -w "$evidence_dir" ] || fail "Evidence directory must exist and be writable: $evidence_dir"
evidence_tmp="$evidence_file.tmp.$$"
umask 077
cat > "$evidence_tmp" <<EOF
{
  "schema_version": 1,
  "environment": "sandbox",
  "probe": "unapproved_database_source",
  "verification_status": "pass",
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source_ip": "$source_ip",
  "approved_application_ip": "$approved_app_ip",
  "database_ip": "$db_ip",
  "database_port": $db_port,
  "connection_result": "rejected"
}
EOF
chmod 400 "$evidence_tmp"
mv -f "$evidence_tmp" "$evidence_file"
echo "SANDBOX_UNAPPROVED_DB_SOURCE=PASS source=$source_ip file=$evidence_file"
