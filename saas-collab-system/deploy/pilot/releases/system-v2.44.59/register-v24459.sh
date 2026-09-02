#!/usr/bin/env bash
# Register a CI-generated, non-secret candidate by calling the root-only
# atomic staging helper. Default is check-only; --apply is the explicit owner
# action that replaces approved-candidate.json atomically.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

source_file=${PILOT_CANDIDATE_SOURCE:-}
apply=0
while (($#)); do
  case "$1" in
    --source=*) source_file=${1#*=} ;;
    --apply) apply=1 ;;
    *) release_fail 'register accepts --source=/absolute/path and optional --apply.' ;;
  esac
  shift
done
require_root
[[ "$source_file" = /* && "$source_file" != *$'\n'* && "$source_file" != *$'\r'* ]] || release_fail 'candidate source must be an absolute newline-free path.'
[[ -f "$source_file" && ! -L "$source_file" ]] || release_fail 'candidate source is missing or unsafe.'
[[ -x /usr/local/sbin/saas-collab-stage-approved-candidate && ! -L /usr/local/sbin/saas-collab-stage-approved-candidate ]] || release_fail 'atomic candidate staging helper is missing.'
if [[ "$apply" -eq 1 ]]; then
  /usr/local/sbin/saas-collab-stage-approved-candidate --source="$source_file"
else
  /usr/local/sbin/saas-collab-stage-approved-candidate --source="$source_file" --check-only
fi
printf 'V24459_REGISTER=%s\n' "$([[ "$apply" -eq 1 ]] && printf applied || printf checked)"
