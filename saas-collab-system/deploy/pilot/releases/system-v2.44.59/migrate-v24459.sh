#!/usr/bin/env bash
# Architecture-controlled migration gate. This script does not run `migrate`
# and cannot bypass the production backup/lock/health gates. The existing
# production-deploy entrypoint runs the reviewed migration service only after
# its root-owned backup hook succeeds.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

[[ "$#" -eq 0 ]] || release_fail 'migration gate accepts no arguments.'
require_root
require_tools
validate_candidate
control_baseline

[[ "${PILOT_ARCHITECT_MIGRATION_APPROVED:-}" = true ]] || release_fail 'architecture must explicitly approve the V2.44.59 migration stage.'
printf 'V24459_MIGRATION_GATE=PASS\n'
printf 'V24459_MIGRATION_EXECUTOR=%s\n' "$CONTROL_ROOT/bin/production-deploy"
printf 'V24459_MIGRATION_POLICY=production-deploy runs backup, lock, reviewed migrate service, health check and automatic rollback; this gate never runs a standalone migration.\n'
