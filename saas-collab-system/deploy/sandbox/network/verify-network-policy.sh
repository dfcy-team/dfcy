#!/usr/bin/env sh
set -eu

mode=${1:-}
policy_file=${2:-/etc/saas-collab/sandbox-network.env}
phase=${3:-current}

fail() {
  echo "Sandbox network verification failed: $*" >&2
  exit 1
}

value() {
  sed -n "s/^$1=//p" "$policy_file" | tail -n 1 | tr -d '\r'
}

[ "$(id -u)" -eq 0 ] || fail "Run as root."
[ -r "$policy_file" ] || fail "Policy file is missing."
case "$phase" in current|post-reboot) ;; *) fail "Verification phase must be current or post-reboot." ;; esac
state_dir=$(value SANDBOX_NETWORK_STATE_DIR)
case "$state_dir" in /*) ;; *) fail "SANDBOX_NETWORK_STATE_DIR must be absolute." ;; esac
case "$mode" in
  app)
    chain=SAAS_SANDBOX_RUNTIME
    subnet=$(docker network inspect saas-sandbox-network --format '{{(index .IPAM.Config 0).Subnet}}')
    db_ip=$(value SANDBOX_DB_HOST_IP)
    db_port=$(value SANDBOX_DB_PORT)
    client_cidr=$(value SANDBOX_CLIENT_CIDR)
    iptables -C DOCKER-USER -j "$chain" || fail "Application policy is not attached."
    iptables -C "$chain" -s "$subnet" -d "$subnet" -j ACCEPT || fail "Internal traffic rule is missing."
    iptables -C "$chain" -s "$client_cidr" -d "$subnet" -p tcp -m multiport --dports 80,443 -j ACCEPT || fail "Client ingress rule is missing."
    iptables -C "$chain" -s "$subnet" -d "$db_ip" -p tcp --dport "$db_port" -j ACCEPT || fail "Database allow rule is missing."
    iptables -C "$chain" -s "$subnet" -j REJECT || fail "Default runtime egress reject is missing."
    ;;
  db)
    chain=SAAS_SANDBOX_DB
    subnet=$(docker network inspect saas-sandbox-db-network --format '{{(index .IPAM.Config 0).Subnet}}')
    app_ip=$(value SANDBOX_APP_HOST_IP)
    iptables -C DOCKER-USER -j "$chain" || fail "Database policy is not attached."
    iptables -C "$chain" -s "$app_ip" -d "$subnet" -p tcp --dport 3306 -j ACCEPT || fail "Application allow rule is missing."
    iptables -C "$chain" -d "$subnet" -p tcp --dport 3306 -j REJECT || fail "Database default reject is missing."
    ;;
  *) fail "Usage: verify-network-policy.sh app|db [policy-file] [current|post-reboot]" ;;
esac

[ -r /etc/iptables/rules.v4 ] || fail "Persistent IPv4 rules file is missing."
grep -q ":$chain " /etc/iptables/rules.v4 || fail "Policy is absent from the persistent IPv4 rule set."
state_file="$state_dir/$mode.applied.env"
[ -r "$state_file" ] || fail "Applied policy state is missing: $state_file"
state_value() {
  sed -n "s/^$1=//p" "$state_file" | tail -n 1 | tr -d '\r'
}
[ "$(state_value SCHEMA_VERSION)" = "1" ] || fail "Applied policy state schema is invalid."
[ "$(state_value MODE)" = "$mode" ] || fail "Applied policy state mode is invalid."
current_policy_hash=$(sha256sum "$policy_file" | cut -d' ' -f1)
current_chain_hash=$(iptables -S "$chain" | sha256sum | cut -d' ' -f1)
[ "$(state_value POLICY_SHA256)" = "$current_policy_hash" ] || fail "Network policy changed after approval."
[ "$(state_value CHAIN_SHA256)" = "$current_chain_hash" ] || fail "Runtime chain differs from the applied policy."
current_boot_id=$(cat /proc/sys/kernel/random/boot_id)
applied_boot_id=$(state_value APPLIED_BOOT_ID)
if [ "$phase" = "post-reboot" ]; then
  [ "$current_boot_id" != "$applied_boot_id" ] || fail "Post-reboot verification requires a host reboot after policy application."
fi
echo "SANDBOX_NETWORK_VERIFY=PASS mode=$mode phase=$phase boot_id=$current_boot_id"
