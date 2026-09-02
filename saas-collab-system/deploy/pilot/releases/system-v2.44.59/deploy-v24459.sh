#!/usr/bin/env bash
# Explicit apply wrapper. No release arguments are accepted: the generic
# runner bridge consumes the owner-staged candidate manifest and invokes the
# existing production-control deploy with all required digest/actor/token
# values. Without --apply this is a safe plan-only check.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1 ;;
    *) release_fail 'deploy accepts only --apply.' ;;
  esac
  shift
done
require_root
require_tools
validate_candidate
if [[ "$apply" -ne 1 ]]; then
  printf 'V24459_DEPLOY_PLAN=READY\n'
  print_candidate_digest
  printf 'V24459_DEPLOY_NEXT=rerun with --apply only after architecture migration approval and final preflight pass.\n'
  exit 0
fi
[[ "${PILOT_ARCHITECT_MIGRATION_APPROVED:-}" = true ]] || release_fail 'architecture migration approval is required before deployment.'
[[ -x /usr/local/sbin/saas-collab-pilot-runner-deploy && ! -L /usr/local/sbin/saas-collab-pilot-runner-deploy ]] || release_fail 'generic runner deploy bridge is missing.'
control_baseline
/usr/local/sbin/saas-collab-pilot-runner-deploy
printf 'V24459_DEPLOY=PASS\n'
