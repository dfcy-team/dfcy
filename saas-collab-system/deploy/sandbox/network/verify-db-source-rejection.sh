#!/usr/bin/env sh
set -eu

action=${1:-}
policy_file=${2:-/etc/saas-collab/sandbox-network.env}

fail() {
  echo "Sandbox database source rejection evidence failed: $*" >&2
  exit 1
}

value() {
  sed -n "s/^$1=//p" "$policy_file" | tail -n 1 | tr -d '\r'
}

[ "$(id -u)" -eq 0 ] || fail "Run as root on the Sandbox database host."
[ -r "$policy_file" ] || fail "Policy file is missing."
state_dir=$(value SANDBOX_NETWORK_STATE_DIR)
case "$state_dir" in /*) ;; *) fail "SANDBOX_NETWORK_STATE_DIR must be absolute." ;; esac
subnet=$(docker network inspect saas-sandbox-db-network --format '{{(index .IPAM.Config 0).Subnet}}')
[ -n "$subnet" ] || fail "Cannot determine the Sandbox database subnet."
reject_packets() {
  iptables -L SAAS_SANDBOX_DB -v -x -n | awk -v subnet="$subnet" '$3 == "REJECT" && $9 == subnet && /tcp dpt:3306/ {total += $1} END {print total + 0}'
}
install -d -m 0700 "$state_dir"
baseline_file="$state_dir/db-source-reject-baseline.env"

case "$action" in
  begin)
    baseline_tmp="$baseline_file.tmp.$$"
    umask 077
    {
      printf 'BOOT_ID=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
      printf 'STARTED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      printf 'REJECT_PACKETS=%s\n' "$(reject_packets)"
    } > "$baseline_tmp"
    chmod 600 "$baseline_tmp"
    mv -f "$baseline_tmp" "$baseline_file"
    echo "SANDBOX_DB_SOURCE_REJECT_BASELINE=READY"
    ;;
  complete)
    [ -r "$baseline_file" ] || fail "Run begin immediately before the independent source probe."
    baseline_value() {
      sed -n "s/^$1=//p" "$baseline_file" | tail -n 1 | tr -d '\r'
    }
    [ "$(baseline_value BOOT_ID)" = "$(cat /proc/sys/kernel/random/boot_id)" ] || fail "Database host rebooted during the source rejection probe."
    before=$(baseline_value REJECT_PACKETS)
    after=$(reject_packets)
    [ "$after" -gt "$before" ] || fail "Database REJECT counter did not increase during the independent source probe."
    evidence_file="$state_dir/db-unapproved-source-reject-evidence.json"
    evidence_tmp="$evidence_file.tmp.$$"
    umask 077
    cat > "$evidence_tmp" <<EOF
{
  "schema_version": 1,
  "environment": "sandbox",
  "probe": "database_unapproved_source_reject_counter",
  "verification_status": "pass",
  "started_at": "$(baseline_value STARTED_AT)",
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "boot_id": "$(cat /proc/sys/kernel/random/boot_id)",
  "reject_packets_before": $before,
  "reject_packets_after": $after
}
EOF
    chmod 400 "$evidence_tmp"
    mv -f "$evidence_tmp" "$evidence_file"
    rm -f "$baseline_file"
    echo "SANDBOX_DB_SOURCE_REJECT_COUNTER=PASS file=$evidence_file"
    ;;
  *) fail "Usage: verify-db-source-rejection.sh begin|complete [policy-file]" ;;
esac
