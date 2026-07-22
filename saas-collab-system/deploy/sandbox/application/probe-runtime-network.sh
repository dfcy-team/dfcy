#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file=${1:-$script_dir/.env.sandbox}
compose_file="$script_dir/docker-compose.sandbox-app.yml"

fail() {
  echo "Sandbox application network probe failed: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

policy_value() {
  sed -n "s/^$1=//p" "$policy_file" | tail -n 1 | tr -d '\r'
}

[ "$(id -u)" -eq 0 ] || fail "Run as root so protected evidence can be written."
[ -r "$env_file" ] || fail "Sandbox environment file is missing."
policy_file=$(env_value SANDBOX_NETWORK_POLICY_FILE)
[ -r "$policy_file" ] || fail "Sandbox network policy file is missing."
state_dir=$(policy_value SANDBOX_NETWORK_STATE_DIR)
case "$state_dir" in /*) ;; *) fail "SANDBOX_NETWORK_STATE_DIR must be absolute." ;; esac
subnet=$(docker network inspect saas-sandbox-network --format '{{(index .IPAM.Config 0).Subnet}}')
[ -n "$subnet" ] || fail "Cannot determine the Sandbox application subnet."
reject_packets() {
  iptables -L SAAS_SANDBOX_RUNTIME -v -x -n | awk -v subnet="$subnet" '$3 == "REJECT" && $8 == subnet {total += $1} END {print total + 0}'
}
reject_before=$(reject_packets)

probe_output=$(docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python - <<'PY'
import os
import socket

with socket.create_connection((os.environ["DB_HOST"], int(os.environ["DB_PORT"])), timeout=5):
    pass
try:
    with socket.create_connection(("1.1.1.1", 443), timeout=3):
        raise SystemExit("Unapproved public egress unexpectedly succeeded.")
except OSError:
    pass
print("SANDBOX_RUNTIME_NETWORK=PASS")
PY
)
printf '%s\n' "$probe_output" | grep -q '^SANDBOX_RUNTIME_NETWORK=PASS$' || fail "Runtime network probe did not pass."
reject_after=$(reject_packets)
[ "$reject_after" -gt "$reject_before" ] || fail "Public egress failed without incrementing the Sandbox REJECT rule counter."

install -d -m 0700 "$state_dir"
evidence_file="$state_dir/app-runtime-network-evidence.json"
evidence_tmp="$evidence_file.tmp.$$"
umask 077
cat > "$evidence_tmp" <<EOF
{
  "schema_version": 1,
  "environment": "sandbox",
  "probe": "application_runtime_network",
  "verification_status": "pass",
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "boot_id": "$(cat /proc/sys/kernel/random/boot_id)",
  "database_destination": "$(env_value DB_HOST):$(env_value DB_PORT)",
  "database_connection": "allowed",
  "public_egress_destination": "1.1.1.1:443",
  "public_egress_connection": "rejected",
  "reject_packets_before": $reject_before,
  "reject_packets_after": $reject_after
}
EOF
chmod 400 "$evidence_tmp"
mv -f "$evidence_tmp" "$evidence_file"
echo "SANDBOX_RUNTIME_NETWORK=PASS file=$evidence_file"
