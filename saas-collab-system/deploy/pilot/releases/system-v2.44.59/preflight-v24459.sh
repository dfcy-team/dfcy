#!/usr/bin/env bash
# Read-only production gate for the V2.44.59 candidate. It never starts a
# container, contacts a registry, reads credential contents, or changes VM
# state. Use PILOT_REMOTE_PREFLIGHT=0 only for an explicitly local dry check.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

[[ "$#" -eq 0 ]] || release_fail 'preflight accepts no arguments.'
require_root
require_tools
validate_candidate
control_baseline
runner_preflight
print_candidate_digest
printf 'V24459_PREFLIGHT=PASS\n'
