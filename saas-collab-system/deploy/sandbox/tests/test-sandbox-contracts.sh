#!/usr/bin/env sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
e2e="$root_dir/application/verify-sandbox-e2e.sh"
network="$root_dir/network"

grep -q '.data.is_superuser == false' "$e2e"
grep -q 'pilot.readiness.view' "$e2e"
grep -q 'environment_ids.*sandbox' "$e2e"
grep -q '\[ "$wrong_status" = "403" \]' "$e2e"
grep -q 'write-artifact-manifest.sh" pass' "$e2e"
grep -q 'network_evidence_sha256' "$root_dir/application/write-artifact-manifest.sh"
grep -q 'Database reject counter evidence' "$root_dir/application/write-artifact-manifest.sh"

grep -q 'post-reboot' "$network/verify-network-policy.sh"
grep -q 'APPLIED_BOOT_ID' "$network/apply-app-policy.sh"
grep -q 'APPLIED_BOOT_ID' "$network/apply-db-policy.sh"
grep -q 'public_egress_connection.*rejected' "$root_dir/application/probe-runtime-network.sh"
grep -q 'connection_result.*rejected' "$network/probe-db-source-denied.sh"
grep -q 'REJECT counter did not increase' "$network/verify-db-source-rejection.sh"

single_host="$root_dir/single-host"
grep -q 'SANDBOX_DEPLOYMENT_MODE=single-host' "$single_host/env.sandbox.example"
grep -q 'SANDBOX_DB_BIND_IP.*SANDBOX_DB_PORT.*3306' "$single_host/docker-compose.sandbox-single-host.yml"
grep -q 'SANDBOX_HTTPS_PORT.*8543' "$single_host/env.sandbox.example"
grep -q 'internal: true' "$single_host/docker-compose.sandbox-single-host.yml"
grep -q 'saas-sandbox-network' "$single_host/docker-compose.sandbox-single-host.yml"
grep -q 'saas-sandbox-db-network' "$single_host/docker-compose.sandbox-single-host.yml"
grep -q 'SANDBOX_DB_BIND_IP=10.20.40.119' "$single_host/env.sandbox.example"
grep -q 'Single-host MySQL must bind only' "$single_host/install-single-host.sh"
grep -q 'SANDBOX_DEPLOYMENT_MODE.*single-host' "$network/apply-app-policy.sh"
grep -q 'SANDBOX_DEPLOYMENT_MODE.*single-host' "$network/apply-db-policy.sh"
grep -q 'Direct application-to-database bridge traffic' "$network/verify-network-policy.sh"
grep -q 'Test-NetConnection' "$network/probe-db-source-denied.ps1"
grep -q 'probe_platform.*windows' "$network/probe-db-source-denied.ps1"

echo "SANDBOX_CONTRACT_GUARDS=PASS"
