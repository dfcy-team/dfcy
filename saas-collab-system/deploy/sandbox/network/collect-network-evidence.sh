#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mode=${1:-}
policy_file=${2:-/etc/saas-collab/sandbox-network.env}
phase=${3:-post-reboot}

fail() {
  echo "Sandbox network evidence failed: $*" >&2
  exit 1
}

value() {
  sed -n "s/^$1=//p" "$policy_file" | tail -n 1 | tr -d '\r'
}

[ "$(id -u)" -eq 0 ] || fail "Run as root."
case "$mode" in app|db) ;; *) fail "Usage: collect-network-evidence.sh app|db [policy-file] [current|post-reboot]" ;; esac
[ -r "$policy_file" ] || fail "Policy file is missing."
state_dir=$(value SANDBOX_NETWORK_STATE_DIR)
case "$state_dir" in /*) ;; *) fail "SANDBOX_NETWORK_STATE_DIR must be absolute." ;; esac

"$script_dir/verify-network-policy.sh" "$mode" "$policy_file" "$phase"
chain=SAAS_SANDBOX_RUNTIME
[ "$mode" = "db" ] && chain=SAAS_SANDBOX_DB
install -d -m 0700 "$state_dir"
evidence_file="$state_dir/$mode-$phase-evidence.json"
evidence_tmp="$evidence_file.tmp.$$"
umask 077
cat > "$evidence_tmp" <<EOF
{
  "schema_version": 1,
  "environment": "sandbox",
  "host_role": "$mode",
  "verification_phase": "$phase",
  "verification_status": "pass",
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "boot_id": "$(cat /proc/sys/kernel/random/boot_id)",
  "policy_sha256": "$(sha256sum "$policy_file" | cut -d' ' -f1)",
  "chain_sha256": "$(iptables -S "$chain" | sha256sum | cut -d' ' -f1)",
  "persistent_rules_sha256": "$(sha256sum /etc/iptables/rules.v4 | cut -d' ' -f1)"
}
EOF
chmod 400 "$evidence_tmp"
mv -f "$evidence_tmp" "$evidence_file"
echo "SANDBOX_NETWORK_EVIDENCE=PASS file=$evidence_file"
