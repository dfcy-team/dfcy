#!/usr/bin/env bash
# Explicit emergency rollback wrapper. Reason, actor and registry token are
# never accepted as command-line values; the staged candidate carries the
# reviewed rollback reason and the bridge reads the owner-managed token file.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1 ;;
    *) release_fail 'rollback accepts only --apply.' ;;
  esac
  shift
done
require_root
require_tools
validate_candidate 0
if [[ "$apply" -ne 1 ]]; then
  printf 'V24459_ROLLBACK_PLAN=READY\n'
  print_candidate_digest
  printf 'V24459_ROLLBACK_NEXT=rerun with --apply only under the approved emergency procedure.\n'
  exit 0
fi
[[ -x /usr/local/sbin/saas-collab-pilot-runner-rollback && ! -L /usr/local/sbin/saas-collab-pilot-runner-rollback ]] || release_fail 'generic runner rollback bridge is missing.'
control_baseline
/usr/local/sbin/saas-collab-pilot-runner-rollback
printf 'V24459_ROLLBACK=PASS\n'
