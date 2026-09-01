#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 migration blocked: $*" >&2
  exit 1
}

mode=apply
case "${1:-}" in
  "") ;;
  --plan-only) mode=plan ;;
  *) fail "usage: $0 [--plan-only]" ;;
esac

ensure_evidence_dir
[ "${PILOT_RELEASE_ACTOR:-architect}" = architect ] || fail "only the architect release actor may run the migration."
[ -f "$env_file" ] || fail "missing protected .env.pilot."
[ ! -f "$release_dir/.influencers-migration.cnf" ] || fail "forbidden .influencers-migration.cnf is present; do not use it or change grants."
[ ! -f "$app_dir/.influencers-migration.cnf" ] || fail "forbidden application .influencers-migration.cnf is present; do not use it or change grants."

read_candidate_file
load_compose_chain
application_db_env_args

# The same approved application connection is used for the pre-migration
# backup, plan, and apply. INFLUENCERS_MIGRATOR is intentionally not read or
# substituted: on the formal database it has SELECT-only privileges.
backup_path="$evidence_dir/pre-deploy-v2.44.52.sql.gz"
backup_sha_path="$backup_path.sha256"
[ ! -e "$backup_path" ] || fail "refusing to overwrite an existing pre-deploy backup: $backup_path"
[ ! -e "$backup_sha_path" ] || fail "refusing to overwrite an existing backup checksum: $backup_sha_path"

"${compose[@]}" config --quiet >/dev/null 2>&1 || fail "application base/override Compose chain is invalid."

pre_migrations="$evidence_dir/pre-migrations-masterdata.txt"
plan_file="$evidence_dir/migration-plan-masterdata-0009.txt"
post_migrations="$evidence_dir/post-migrations-masterdata.txt"

# Run the read-only migration state and plan against the candidate image. No
# generic `migrate` target is invoked, and no other Django app is included.
"${compose[@]}" run --rm --no-deps "${migration_env[@]}" \
  --entrypoint python backend manage.py showmigrations masterdata \
  > "$pre_migrations" 2>&1 || fail "unable to read pre-migration state."
grep -Eq '^[[:space:]]*\[[Xx]\][[:space:]]+0008_' "$pre_migrations" || fail "required masterdata.0008 baseline is not applied."
if grep -Eq '^[[:space:]]*\[[Xx]\][[:space:]]+0009_warehouse_service_platform' "$pre_migrations"; then
  fail "masterdata.0009 is already applied; refusing a duplicate release migration."
fi

"${compose[@]}" run --rm --no-deps "${migration_env[@]}" \
  --entrypoint python backend manage.py migrate masterdata 0009_warehouse_service_platform --plan \
  > "$plan_file" 2>&1 || fail "unable to obtain the masterdata.0009 migration plan."
# Django's --plan output is normally `masterdata.0009_...` without a checkbox;
# accept the checkbox form too, but count migration header lines so a second
# pending migration can never pass this gate.
planned_migrations=$(sed -nE 's/^[[:space:]]*(\[[^]]+\][[:space:]]+)?([a-z][a-z0-9_]*)\.([0-9]{4}_[a-z0-9_]+)[[:space:]]*$/\2.\3/p' "$plan_file")
[ "$planned_migrations" = masterdata.0009_warehouse_service_platform ] || \
  fail "migration plan is not exactly masterdata.0009_warehouse_service_platform."

if [ "$mode" = plan ]; then
  echo "V2.44.52 MIGRATION_PLAN=PASS migration=masterdata.0009_warehouse_service_platform backup=not-created mode=plan-only"
  exit 0
fi

# Dump with MYSQL_PWD so the application password is never a command-line
# argument. The dump remains outside Git and its contents are never printed.
command -v mysqldump >/dev/null 2>&1 || fail "mysqldump is required for the pre-migration backup."
command -v gzip >/dev/null 2>&1 || fail "gzip is required for the pre-migration backup."
(
  umask 077
  MYSQL_PWD="$db_password" mysqldump --no-tablespaces --single-transaction --quick --skip-lock-tables \
    -h "$db_host" -P "$db_port" -u "$db_user" "$db_name" \
    | gzip -c > "$backup_path"
)
[ -s "$backup_path" ] || fail "pre-migration database backup is empty."
gzip -t "$backup_path" || fail "pre-migration database backup failed gzip integrity."
sha256sum "$backup_path" > "$backup_sha_path"
chmod 600 "$backup_path" "$backup_sha_path"

"${compose[@]}" run --rm --no-deps "${migration_env[@]}" \
  --entrypoint python migrate manage.py migrate masterdata 0009_warehouse_service_platform --noinput \
  > "$evidence_dir/migration-masterdata-0009.stdout" 2> "$evidence_dir/migration-masterdata-0009.stderr" \
  || fail "masterdata.0009 migration failed; inspect the redacted status and preserve the backup."

"${compose[@]}" run --rm --no-deps "${migration_env[@]}" \
  --entrypoint python backend manage.py showmigrations masterdata \
  > "$post_migrations" 2>&1 || fail "unable to read post-migration state."
grep -Eq '^[[:space:]]*\[[Xx]\][[:space:]]+0009_warehouse_service_platform' "$post_migrations" || \
  fail "masterdata.0009 is not marked applied after migration."

printf 'BACKUP_VALIDATION=PASS\nBACKUP_PATH=%s\nBACKUP_SHA256=%s\nDATABASE_ACCOUNT=%s\nDATABASE_NAME=%s\nMIGRATION_PLAN=masterdata.0009_warehouse_service_platform\nMIGRATION_APPLY=PASS\n' \
  "$backup_path" "$(cut -d' ' -f1 "$backup_sha_path")" "$db_user" "$db_name" \
  > "$evidence_dir/migration-status.txt"
chmod 600 "$evidence_dir/migration-status.txt"
echo "V2.44.52 MIGRATION=PASS migration=masterdata.0009_warehouse_service_platform backup=PASS database_account=$db_user database=$db_name"
