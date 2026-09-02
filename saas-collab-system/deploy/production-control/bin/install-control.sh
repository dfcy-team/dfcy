#!/usr/bin/env bash
# Owner-only installation of the fixed production release control plane.
# This script is run on the VM from a reviewed checkout. It never copies a
# live dotenv file or an SSH private key.
set -Eeuo pipefail

SOURCE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CONTROL_ROOT="/opt/saas-collab/release-control/unified"
DEPLOY_USER="dfcy01"
LIVE_ENV_FILE=""
FORCE=0
INITIALIZE_BASELINE=0
WRITE_SUDOERS=0

fail() {
  printf 'Production control installation blocked: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --control-root=*) CONTROL_ROOT=${1#*=} ;;
    --deploy-user=*) DEPLOY_USER=${1#*=} ;;
    --env-file=*) LIVE_ENV_FILE=${1#*=} ;;
    --force) FORCE=1 ;;
    --initialize-baseline) INITIALIZE_BASELINE=1 ;;
    --write-sudoers) WRITE_SUDOERS=1 ;;
    --help)
      printf '%s\n' 'Usage: install-control.sh [--control-root=ABS] [--deploy-user=USER] [--env-file=ABS] [--force] [--initialize-baseline] [--write-sudoers]'
      exit 0
      ;;
    *) fail 'unknown installation option.' ;;
  esac
  shift
done

[[ "$(id -u)" -eq 0 ]] || fail 'run this owner installation as root.'
[[ "$CONTROL_ROOT" = /* && "$CONTROL_ROOT" != *[[:space:]]* ]] || fail 'control root must be an absolute path without whitespace.'
[[ "$DEPLOY_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || fail 'deploy user is invalid.'
[[ -d "$SOURCE_ROOT/bin" && -d "$SOURCE_ROOT/lib" ]] || fail 'the production-control source tree is incomplete.'

if [[ -e "$CONTROL_ROOT/bin/production-deploy" && "$FORCE" -ne 1 ]]; then
  fail 'control files already exist; use --force only after reviewing the diff.'
fi

mkdir -p "$CONTROL_ROOT/bin" "$CONTROL_ROOT/lib" "$CONTROL_ROOT/config" "$CONTROL_ROOT/ledger" "$CONTROL_ROOT/releases" "$CONTROL_ROOT/locks"
chmod 755 "$CONTROL_ROOT" "$CONTROL_ROOT/bin" "$CONTROL_ROOT/lib"
chmod 700 "$CONTROL_ROOT/config" "$CONTROL_ROOT/ledger" "$CONTROL_ROOT/releases" "$CONTROL_ROOT/locks"

for file in \
  developer-a-ci-dispatch \
  production-deploy \
  production-rollback \
  production-health-check \
  production-backup \
  production-baseline-check \
  adopt-current.sh \
  install-control.sh; do
  install -o root -g root -m 0755 "$SOURCE_ROOT/bin/$file" "$CONTROL_ROOT/bin/$file"
done
install -o root -g root -m 0644 "$SOURCE_ROOT/lib/production-common.sh" "$CONTROL_ROOT/lib/production-common.sh"
install -o root -g root -m 0644 "$SOURCE_ROOT/production-compose.yml" "$CONTROL_ROOT/production-compose.yml"

if [[ -n "$LIVE_ENV_FILE" ]]; then
  [[ "$LIVE_ENV_FILE" = /* && ! -L "$LIVE_ENV_FILE" ]] || fail 'live environment path must be an absolute, non-symlink path.'
  [[ -f "$LIVE_ENV_FILE" ]] || fail 'the specified live environment file does not exist.'
  printf '%s\n' "$LIVE_ENV_FILE" > "$CONTROL_ROOT/config/env.path"
  chmod 600 "$CONTROL_ROOT/config/env.path"
  chown root:root "$CONTROL_ROOT/config/env.path"
elif [[ -f "$CONTROL_ROOT/config/env.path" ]]; then
  chmod 600 "$CONTROL_ROOT/config/env.path"
else
  printf '%s\n' "$CONTROL_ROOT/config/.env.production" > "$CONTROL_ROOT/config/env.path"
  chmod 600 "$CONTROL_ROOT/config/env.path"
fi

if [[ "$INITIALIZE_BASELINE" -eq 1 ]]; then
  baseline="$CONTROL_ROOT/config/baseline.sha256"
  [[ ! -e "$baseline" || "$FORCE" -eq 1 ]] || fail 'baseline exists; use --force only after reviewing the control-file changes.'
  tmp=$(mktemp "$CONTROL_ROOT/config/.baseline.XXXXXX")
  trap 'rm -f -- "$tmp"' EXIT HUP INT TERM
  (
    cd "$CONTROL_ROOT"
    sha256sum \
      bin/developer-a-ci-dispatch \
      bin/production-deploy \
      bin/production-rollback \
      bin/production-health-check \
      bin/production-backup \
      bin/production-baseline-check \
      lib/production-common.sh \
      production-compose.yml
    control_env="$CONTROL_ROOT/config/control.env"
    if [[ -f "$control_env" ]]; then
      [[ ! -L "$control_env" ]] || fail 'the control environment file is unsafe.'
      sha256sum "$control_env"
    fi
    baseline_env_file="$LIVE_ENV_FILE"
    if [[ -z "$baseline_env_file" && -f "$CONTROL_ROOT/config/env.path" ]]; then
      IFS= read -r baseline_env_file < "$CONTROL_ROOT/config/env.path" || true
    fi
    if [[ -n "$baseline_env_file" && -f "$baseline_env_file" ]]; then
      compose_list=$(sed -n 's/^PRODUCTION_COMPOSE_FILES=//p' "$baseline_env_file" | tail -n 1 | tr -d '\r')
    fi
    if [[ -f "$control_env" ]]; then
      control_compose_list=$(sed -n 's/^PRODUCTION_COMPOSE_FILES=//p' "$control_env" | tail -n 1 | tr -d '\r')
      if [[ -n "$control_compose_list" ]]; then
        compose_list=$control_compose_list
      fi
    fi
    if [[ -n "${compose_list:-}" ]]; then
      IFS=: read -r -a compose_files <<< "$compose_list"
      for compose_file in "${compose_files[@]}"; do
        [[ "$compose_file" = /* && -f "$compose_file" && ! -L "$compose_file" ]] || fail 'a configured Compose file is missing or unsafe.'
        sha256sum "$compose_file"
      done
    fi
  ) > "$tmp"
  chmod 600 "$tmp"
  chown root:root "$tmp"
  mv -f -- "$tmp" "$baseline"
  chmod 600 "$baseline"
  trap - EXIT HUP INT TERM
fi

if [[ "$WRITE_SUDOERS" -eq 1 ]]; then
  require_visudo=0
  command -v visudo >/dev/null 2>&1 && require_visudo=1
  sudoers_file="/etc/sudoers.d/saas-collab-release-control"
  tmp_sudoers=$(mktemp /etc/sudoers.d/.saas-collab-release-control.XXXXXX)
  trap 'rm -f -- "$tmp_sudoers"' EXIT HUP INT TERM
  {
    printf 'Cmnd_Alias SAAS_COLLAB_RELEASE_CONTROL = %s/bin/production-deploy *, %s/bin/production-rollback *, %s/bin/production-baseline-check --runtime\n' "$CONTROL_ROOT" "$CONTROL_ROOT" "$CONTROL_ROOT"
    printf '%s ALL=(root) NOPASSWD: SAAS_COLLAB_RELEASE_CONTROL\n' "$DEPLOY_USER"
  } > "$tmp_sudoers"
  chmod 440 "$tmp_sudoers"
  chown root:root "$tmp_sudoers"
  if [[ "$require_visudo" -eq 1 ]]; then
    visudo -cf "$tmp_sudoers" >/dev/null || fail 'generated sudoers policy failed validation.'
  fi
  mv -f -- "$tmp_sudoers" "$sudoers_file"
  chmod 440 "$sudoers_file"
  trap - EXIT HUP INT TERM
fi

chown -R root:root "$CONTROL_ROOT/bin" "$CONTROL_ROOT/lib" "$CONTROL_ROOT/config" "$CONTROL_ROOT/production-compose.yml"
printf 'PRODUCTION_CONTROL_INSTALL=PASS\n'
