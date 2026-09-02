#!/usr/bin/env bash
# Read-only post-deploy verification. The current ledger must now point to the
# approved candidate SHA; health and baseline checks remain the source of truth.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

[[ "$#" -eq 0 ]] || release_fail 'post-verify accepts no arguments.'
require_root
require_tools
validate_candidate 0
[[ -x "$CONTROL_ROOT/bin/production-health-check" && ! -L "$CONTROL_ROOT/bin/production-health-check" ]] || release_fail 'production health checker is missing.'
control_baseline
current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || release_fail 'current release ledger is invalid.'
candidate_sha=$(jq -er '.release_sha' "$CANDIDATE_FILE") || release_fail 'candidate release SHA is invalid.'
[[ "$current_sha" = "$candidate_sha" ]] || release_fail 'current ledger does not reference the approved V2.44.59 candidate.'
"$CONTROL_ROOT/bin/production-health-check" --quiet >/dev/null || release_fail 'production health check failed.'
printf 'V24459_POST_VERIFY=PASS\n'
printf 'V24459_CURRENT_SHA=%s\n' "$current_sha"
