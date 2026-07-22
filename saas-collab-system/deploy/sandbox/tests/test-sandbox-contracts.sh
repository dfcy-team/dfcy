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

echo "SANDBOX_CONTRACT_GUARDS=PASS"
