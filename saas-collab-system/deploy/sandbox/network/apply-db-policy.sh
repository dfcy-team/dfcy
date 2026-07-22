#!/usr/bin/env sh
set -eu

policy_file=${1:-/etc/saas-collab/sandbox-network.env}
chain=SAAS_SANDBOX_DB

fail() {
  echo "Sandbox database network policy blocked: $*" >&2
  exit 1
}

value() {
  sed -n "s/^$1=//p" "$policy_file" | tail -n 1 | tr -d '\r'
}

[ "$(id -u)" -eq 0 ] || fail "Run as root."
[ -r "$policy_file" ] || fail "Policy file is missing: $policy_file"
[ "$(value SANDBOX_NETWORK_APPLY)" = "YES" ] || fail "SANDBOX_NETWORK_APPLY must be YES."
command -v iptables >/dev/null 2>&1 || fail "iptables is required."
command -v netfilter-persistent >/dev/null 2>&1 || fail "netfilter-persistent is required."
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required."

app_ip=$(value SANDBOX_APP_HOST_IP)
state_dir=$(value SANDBOX_NETWORK_STATE_DIR)
case "$state_dir" in /*) ;; *) fail "SANDBOX_NETWORK_STATE_DIR must be absolute." ;; esac
case "$app_ip" in 10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) ;; *) fail "Application IP must be private." ;; esac
subnet=$(docker network inspect saas-sandbox-db-network --format '{{(index .IPAM.Config 0).Subnet}}')
[ -n "$subnet" ] || fail "Cannot determine saas-sandbox-db-network subnet."
iptables -S DOCKER-USER >/dev/null 2>&1 || fail "DOCKER-USER chain is unavailable."
iptables -N "$chain" 2>/dev/null || true
iptables -F "$chain"
iptables -A "$chain" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A "$chain" -s "$app_ip" -d "$subnet" -p tcp --dport 3306 -j ACCEPT
iptables -A "$chain" -d "$subnet" -p tcp --dport 3306 -j REJECT
iptables -A "$chain" -s "$subnet" -j REJECT
iptables -A "$chain" -j RETURN
iptables -C DOCKER-USER -j "$chain" 2>/dev/null || iptables -I DOCKER-USER 1 -j "$chain"
netfilter-persistent save >/dev/null
install -d -m 0700 "$state_dir"
policy_hash=$(sha256sum "$policy_file" | cut -d' ' -f1)
chain_hash=$(iptables -S "$chain" | sha256sum | cut -d' ' -f1)
state_tmp="$state_dir/db.applied.env.tmp.$$"
umask 077
{
  printf 'SCHEMA_VERSION=1\n'
  printf 'MODE=db\n'
  printf 'APPLIED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'APPLIED_BOOT_ID=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
  printf 'POLICY_SHA256=%s\n' "$policy_hash"
  printf 'CHAIN_SHA256=%s\n' "$chain_hash"
} > "$state_tmp"
chmod 600 "$state_tmp"
mv -f "$state_tmp" "$state_dir/db.applied.env"
echo "SANDBOX_DB_NETWORK_POLICY=PASS subnet=$subnet"
