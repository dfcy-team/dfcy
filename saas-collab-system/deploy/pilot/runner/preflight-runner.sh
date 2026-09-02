#!/usr/bin/env bash
# Read-only runner/VM preflight.  It never starts services, changes ownership,
# reads credential contents, opens SSH, or contacts a registry.
set -Eeuo pipefail

CONFIG_ROOT=${PILOT_RUNNER_CONFIG_ROOT:-/etc/saas-collab/runner}
CONFIG_FILE=${PILOT_RUNNER_CONFIG_FILE:-$CONFIG_ROOT/config.json}
MANIFEST_FILE=${PILOT_RUNNER_MANIFEST_FILE:-$CONFIG_ROOT/approved-candidate.json}
TOKEN_FILE=${PILOT_RUNNER_TOKEN_FILE:-$CONFIG_ROOT/secrets/runner.token}
REGISTRY_TOKEN_FILE=${PILOT_RUNNER_REGISTRY_TOKEN_FILE:-$CONFIG_ROOT/registry-token}
CONTROL_ROOT=${PILOT_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/unified}
RUNNER_USER=${PILOT_RUNNER_USER:-saas-runner}
REMOTE_PREFLIGHT=${PILOT_REMOTE_PREFLIGHT:-1}
VM_HOST=${PILOT_VM_HOST:-192.168.2.10}
VM_SSH_PORT=${PILOT_VM_SSH_PORT:-22131}

fail() {
  printf 'pilot runner preflight blocked: %s\n' "$*" >&2
  exit 1
}

regular_file() {
  local path=$1 label=$2 modes=$3 expected_owner=${4:-} expected_group=${5:-} mode owner group
  [[ "$path" = /* && -f "$path" && ! -L "$path" ]] || fail "$label is missing or unsafe."
  mode=$(stat -c '%a' "$path" 2>/dev/null) || fail "cannot inspect $label mode."
  case ",$modes," in *",$mode,"*) ;; *) fail "$label has an unsafe mode." ;; esac
  owner=$(stat -c '%U' "$path" 2>/dev/null) || fail "cannot inspect $label owner."
  group=$(stat -c '%G' "$path" 2>/dev/null) || fail "cannot inspect $label group."
  if [[ -n "$expected_owner" ]]; then
    [[ "$owner" = "$expected_owner" ]] || fail "$label owner is not controlled."
  else
    [[ "$owner" = root || ( "$label" = runner-token && "$owner" = "$RUNNER_USER" ) ]] || fail "$label owner is not controlled."
  fi
  [[ -z "$expected_group" || "$group" = "$expected_group" ]] || fail "$label group is not controlled."
}

directory() {
  local path=$1 label=$2 expected_owner=${3:-} expected_group=${4:-} expected_modes=${5:-700,750,755} owner group mode
  [[ "$path" = /* && -d "$path" && ! -L "$path" ]] || fail "$label is missing or unsafe."
  owner=$(stat -c '%U' "$path" 2>/dev/null) || fail "cannot inspect $label owner."
  group=$(stat -c '%G' "$path" 2>/dev/null) || fail "cannot inspect $label group."
  [[ -z "$expected_owner" || "$owner" = "$expected_owner" ]] || fail "$label owner is not controlled."
  [[ -z "$expected_group" || "$group" = "$expected_group" ]] || fail "$label group is not controlled."
  mode=$(stat -c '%a' "$path" 2>/dev/null) || fail "cannot inspect $label mode."
  case ",$expected_modes," in *",$mode,"*) ;; *) fail "$label has an unexpected mode." ;; esac
}

runner_readable() {
  local path=$1 label=$2
  command -v runuser >/dev/null 2>&1 || fail 'runuser is required to verify runner file readability.'
  runuser -u "$RUNNER_USER" -- test -r "$path" || fail "$label is not readable by $RUNNER_USER."
}

[[ "$(id -u)" -eq 0 ]] || fail 'run runner preflight as root.'
command -v jq >/dev/null 2>&1 || fail 'jq is required.'
command -v stat >/dev/null 2>&1 || fail 'stat is required.'
directory "$CONFIG_ROOT" runner-config-directory root "$RUNNER_USER" 750
directory "$CONFIG_ROOT/secrets" runner-secrets-directory root "$RUNNER_USER" 750
directory "$CONFIG_ROOT/tls" runner-tls-directory root "$RUNNER_USER" 750
regular_file "$CONFIG_FILE" runner-config '400,440,600,640' root "$RUNNER_USER"
regular_file "$MANIFEST_FILE" candidate-manifest '440,640' root "$RUNNER_USER"
regular_file "$TOKEN_FILE" runner-token '440,640' root "$RUNNER_USER"
# The registry credential is consumed only by the root bridge, never by the
# runner process; keep it inaccessible to saas-runner even though its parent
# directory is traversable by that service.
regular_file "$REGISTRY_TOKEN_FILE" registry-token '400,600' root root
regular_file "$CONFIG_ROOT/tls/runner.crt" runner-tls-certificate '400,440,600,640,644' root "$RUNNER_USER"
regular_file "$CONFIG_ROOT/tls/runner.key" runner-tls-private-key '440,640' root "$RUNNER_USER"
runner_readable "$CONFIG_FILE" runner-config
runner_readable "$MANIFEST_FILE" candidate-manifest
runner_readable "$TOKEN_FILE" runner-token
runner_readable "$CONFIG_ROOT/tls/runner.crt" runner-tls-certificate
runner_readable "$CONFIG_ROOT/tls/runner.key" runner-tls-private-key
directory /var/lib/saas-collab/pilot-runner runner-state-directory "$RUNNER_USER" "$RUNNER_USER" 700
directory /var/lib/saas-collab/pilot-runner/evidence runner-evidence-directory "$RUNNER_USER" "$RUNNER_USER" 700

manifest_version=$(jq -er '.release_version' "$MANIFEST_FILE") || fail 'candidate manifest JSON is invalid.'
manifest_parent=$(jq -er '.parent_release' "$MANIFEST_FILE") || fail 'candidate parent is missing.'
manifest_parent_sha=$(jq -er '.parent_release_sha' "$MANIFEST_FILE") || fail 'candidate parent SHA is missing.'
manifest_release_sha=$(jq -er '.release_sha' "$MANIFEST_FILE") || fail 'candidate release SHA is missing.'
plan_version=$(jq -er '.release_plan.version' "$MANIFEST_FILE") || fail 'candidate release plan is missing.'
plan_ref=$(jq -er '.release_plan.ref' "$MANIFEST_FILE") || fail 'candidate release plan ref is missing.'
current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || fail 'production current ledger release SHA is missing.'
current_version=$(jq -er '.release_version // empty' "$CONTROL_ROOT/current.json") || fail 'production current ledger JSON is invalid.'
[[ "$manifest_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$manifest_parent" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$plan_version" = "$manifest_version" ]] || fail 'candidate manifest version/parent/release plan is invalid.'
[[ "$manifest_parent_sha" = "$current_sha" && "$manifest_release_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'candidate parent SHA does not match the production current ledger.'
[[ -z "$current_version" || "$current_version" = "$manifest_parent" ]] || fail 'candidate parent version does not match the production current ledger.'
[[ "$plan_ref" =~ ^[A-Za-z0-9_.:/-]{1,200}$ ]] || fail 'candidate release plan ref is invalid.'
jq -e '.ci_attestation.main_ancestry == true and .ci_attestation.image_digests == true and .ci_attestation.migration_digest == true' "$MANIFEST_FILE" >/dev/null || fail 'candidate CI attestation is incomplete.'

for path in "$CONTROL_ROOT" "$CONTROL_ROOT/bin" "$CONTROL_ROOT/lib" "$CONTROL_ROOT/config" "$CONTROL_ROOT/ledger" "$CONTROL_ROOT/releases" "$CONTROL_ROOT/config/baseline.sha256" "$CONTROL_ROOT/current.json" "$CONTROL_ROOT/previous.json" "$CONTROL_ROOT/production-compose.yml"; do
  [[ -e "$path" && ! -L "$path" ]] || fail "production control path is missing or symbolic: $path"
  owner=$(stat -c '%U' "$path" 2>/dev/null) || fail 'cannot inspect production control owner.'
  [[ "$owner" = root ]] || fail 'production control tree must be root-owned.'
  mode=$(stat -c '%a' "$path" 2>/dev/null) || fail 'cannot inspect production control mode.'
  (( (8#$mode & 0022) == 0 )) || fail 'production control tree must not be group/world writable.'
done

if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx docker; then
  fail 'runner user must not belong to docker group.'
fi
[[ -x "$CONTROL_ROOT/bin/production-baseline-check" && ! -L "$CONTROL_ROOT/bin/production-baseline-check" ]] || fail 'production baseline checker is missing.'
"$CONTROL_ROOT/bin/production-baseline-check" --runtime >/dev/null || fail 'production runtime baseline/backup gate failed.'
systemd_file=/etc/systemd/system/saas-collab-pilot-runner.service
regular_file "$systemd_file" systemd-unit '400,440,600,640,644'
grep -Fq 'InaccessiblePaths=/var/run/docker.sock /run/docker.sock' "$systemd_file" || fail 'systemd unit must hide Docker sockets.'

if [[ "$REMOTE_PREFLIGHT" = 1 ]]; then
  [[ "$VM_HOST" =~ ^[A-Za-z0-9_.-]+$ && "$VM_SSH_PORT" =~ ^[0-9]+$ && "$VM_SSH_PORT" -ge 1 && "$VM_SSH_PORT" -le 65535 ]] || fail 'VM SSH preflight target is invalid.'
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 2 "$VM_HOST" "$VM_SSH_PORT" >/dev/null 2>&1 || fail "FIELD_SWITCH_BLOCKED_SSH: $VM_HOST:$VM_SSH_PORT is not reachable."
  else
    command -v timeout >/dev/null 2>&1 || fail 'nc or timeout is required for SSH preflight.'
    timeout 3 bash -c "</dev/tcp/$VM_HOST/$VM_SSH_PORT" >/dev/null 2>&1 || fail "FIELD_SWITCH_BLOCKED_SSH: $VM_HOST:$VM_SSH_PORT is not reachable."
  fi
fi

printf 'PILOT_RUNNER_PREFLIGHT=PASS\n'
printf 'PILOT_RUNNER_CANDIDATE=%s\n' "$manifest_version"
printf 'PILOT_RUNNER_PARENT=%s\n' "$manifest_parent"
printf 'PILOT_RUNNER_SSH_PREFLIGHT=%s\n' "$([[ "$REMOTE_PREFLIGHT" = 1 ]] && printf required || printf skipped-local)"
