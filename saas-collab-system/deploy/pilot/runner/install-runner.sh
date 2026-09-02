#!/usr/bin/env bash
# Owner-only installation of the standalone pilot runner.  This script
# creates directories and fixed wrappers only; it never creates, reads, or
# prints a credential and never mounts a Docker socket.
set -Eeuo pipefail

SOURCE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_ROOT=/opt/saas-collab/pilot-runner
CONFIG_ROOT=/etc/saas-collab/runner
STATE_ROOT=/var/lib/saas-collab/pilot-runner
RUNNER_USER=saas-runner
FORCE=0

fail() {
  printf 'pilot runner installation blocked: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --install-root=*) INSTALL_ROOT=${1#*=} ;;
    --config-root=*) CONFIG_ROOT=${1#*=} ;;
    --state-root=*) STATE_ROOT=${1#*=} ;;
    --runner-user=*) RUNNER_USER=${1#*=} ;;
    --force) FORCE=1 ;;
    --help)
      printf '%s\n' 'Usage: install-runner.sh [--install-root=ABS] [--config-root=ABS] [--state-root=ABS] [--runner-user=USER] [--force]'
      exit 0
      ;;
    *) fail 'unknown installation option.' ;;
  esac
  shift
done

[[ "$(id -u)" -eq 0 ]] || fail 'run this installation as root.'
for path in "$INSTALL_ROOT" "$CONFIG_ROOT" "$STATE_ROOT"; do
  [[ "$path" = /* && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || fail 'installation paths must be absolute and newline-free.'
done
[[ -f "$SOURCE_ROOT/../../../pilot-runner/app.py" ]] || fail 'runner application source is missing.'

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  command -v useradd >/dev/null 2>&1 || fail 'runner user does not exist and useradd is unavailable.'
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin "$RUNNER_USER"
fi
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx docker; then
  fail 'runner user must not belong to the docker group.'
fi

install -d -o root -g root -m 0755 "$INSTALL_ROOT"
# The runner must be able to traverse the root-owned configuration tree while
# remaining unable to write it.  A root:root 0750 directory would make the
# root:saas-runner 0440 candidate/TLS files below unreadable to the service.
install -d -o root -g "$RUNNER_USER" -m 0750 "$CONFIG_ROOT"
install -d -o root -g "$RUNNER_USER" -m 0750 "$CONFIG_ROOT/secrets" "$CONFIG_ROOT/tls"
install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$STATE_ROOT" "$STATE_ROOT/evidence"
install -d -o root -g root -m 0755 /usr/local/lib/saas-collab

install -o root -g root -m 0755 "$SOURCE_ROOT/../../../pilot-runner/app.py" "$INSTALL_ROOT/app.py"
if [[ ! -e "$CONFIG_ROOT/config.json" || "$FORCE" -eq 1 ]]; then
  install -o root -g "$RUNNER_USER" -m 0640 "$SOURCE_ROOT/../../../pilot-runner/config.example.json" "$CONFIG_ROOT/config.json.example"
fi

install -o root -g root -m 0644 "$SOURCE_ROOT/bin/runner-action-common.sh" /usr/local/lib/saas-collab/pilot-runner-action-common.sh
install -o root -g root -m 0755 "$SOURCE_ROOT/bin/stage-approved-candidate.sh" /usr/local/sbin/saas-collab-stage-approved-candidate
install -o root -g root -m 0755 "$SOURCE_ROOT/preflight-runner.sh" /usr/local/sbin/saas-collab-pilot-runner-preflight
for wrapper in runner-deploy runner-recovery runner-rollback; do
  install -o root -g root -m 0755 "$SOURCE_ROOT/bin/$wrapper" "/usr/local/sbin/saas-collab-pilot-$wrapper"
done

# Keep the command bridge narrow.  The bridge itself has no user-supplied
# arguments; it reads only the owner-prepared manifest and token file.
sudoers_file=/etc/sudoers.d/saas-collab-pilot-runner
tmp_sudoers=$(mktemp /etc/sudoers.d/.saas-collab-pilot-runner.XXXXXX)
trap 'rm -f -- "$tmp_sudoers"' EXIT HUP INT TERM
{
  printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/saas-collab-pilot-runner-deploy, /usr/local/sbin/saas-collab-pilot-runner-recovery, /usr/local/sbin/saas-collab-pilot-runner-rollback\n' "$RUNNER_USER"
} > "$tmp_sudoers"
chmod 440 "$tmp_sudoers"
chown root:root "$tmp_sudoers"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$tmp_sudoers" >/dev/null || fail 'runner sudoers policy failed validation.'
fi
mv -f -- "$tmp_sudoers" "$sudoers_file"
trap - EXIT HUP INT TERM
chmod 440 "$sudoers_file"
chown root:root "$sudoers_file"

install -o root -g root -m 0644 "$SOURCE_ROOT/runner.service" /etc/systemd/system/saas-collab-pilot-runner.service
printf 'PILOT_RUNNER_INSTALL=PASS\n'
printf 'PILOT_RUNNER_NEXT=provision config.json, TLS files, runner token, candidate manifest, and registry token as owner-managed files; then run preflight-runner.sh.\n'
