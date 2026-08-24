#!/usr/bin/env bash
set -euo pipefail

# Prepare an isolated staging database from the developer-B data snapshot.
# Source INSERT statements are rewritten to the explicitly named stage DB.
#
# Required: DATA_DUMP=/secure/influencers_data_34.sql.gz
#           DB_USER=... DB_PASSWORD=...
# Optional: DB_HOST=127.0.0.1 DB_PORT=3306
#           TARGET_DB=saas_collab_pilot
#           STAGE_DB=saas_collab_influencers_stage_20260824

target_db=${TARGET_DB:-saas_collab_pilot}
stage_db=${STAGE_DB:-saas_collab_influencers_stage_20260824}
data_dump=${DATA_DUMP:?set DATA_DUMP to influencers_data_34.sql.gz}
db_host=${DB_HOST:-127.0.0.1}
db_port=${DB_PORT:-3306}
db_user=${DB_USER:?set DB_USER}
db_password=${DB_PASSWORD:?set DB_PASSWORD}

case "$target_db" in (*[!A-Za-z0-9_]*|'') echo "invalid TARGET_DB" >&2; exit 2;; esac
case "$stage_db" in (*[!A-Za-z0-9_]*|'') echo "invalid STAGE_DB" >&2; exit 2;; esac
test "$target_db" != "$stage_db"
test -s "$data_dump"
command -v mysql >/dev/null
command -v gzip >/dev/null
command -v sed >/dev/null

expected_data_sha256=${SOURCE_DATA_SHA256:-d09c99912f4ccc10f7c5e09fead47b5860c547b0f677f55ac6b7ea63b814bc5b}
actual_data_sha256=$(sha256sum "$data_dump" | awk '{print $1}')
test "$actual_data_sha256" = "$expected_data_sha256"

mysql_cmd=(mysql --protocol=tcp --host="$db_host" --port="$db_port" --user="$db_user" --default-character-set=utf8mb4 --batch --skip-column-names)
export MYSQL_PWD="$db_password"

tables=(
  influencers_affiliateimportstate
  influencers_affiliateorderrevision
  influencers_affiliateordersnapshot
  influencers_bdorderattributionsnapshot
  influencers_bdsampleattributionsnapshot
  influencers_bdvideoattribution
  influencers_bdvideoattributioncurrent
  influencers_exchangerate
  influencers_externalsourcerecord
  influencers_fulfillmentstatusevent
  influencers_importbatch
  influencers_influencer
  influencers_influencercontact
  influencers_influencerprofile
  influencers_influencerrestrictevent
  influencers_influencerrestriction
  influencers_outreachtarget
  influencers_outreachtask
  influencers_samplefulfillment
  influencers_sampleitem
  influencers_skupricesnapshot
  influencers_storeproductlisting
  influencers_tiktokshopvideo
  influencers_tiktokvideodailymetric
  influencers_tiktokvideoproduct
  influencers_tiktokvideosyncbatch
  influencers_videoresult
)

# Existing non-empty stages are rejected. Choose a new stage name for a
# separate audit instead of clearing a prior staging database.
"${mysql_cmd[@]}" -e "CREATE DATABASE IF NOT EXISTS $stage_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
for table in "${tables[@]}"; do
  existing=$("${mysql_cmd[@]}" -e \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$stage_db' AND table_name='$table';")
  if [[ "$existing" == "1" ]]; then
    rows=$("${mysql_cmd[@]}" -e "SELECT COUNT(*) FROM $stage_db.$table;")
    test "$rows" = "0" || {
      echo "staging table $table is not empty; choose a new STAGE_DB" >&2
      exit 3
    }
  else
    "${mysql_cmd[@]}" -e "CREATE TABLE $stage_db.$table LIKE $target_db.$table;"
  fi
done

# The dump contains source primary keys and source foreign-key values. They
# remain only in stage. The migration script resolves every relation before
# writing tenant-owned target rows. The dump's FK toggle is removed from the
# staging stream; target FKs are never disabled.
gzip -dc "$data_dump" \
  | sed -E '/FOREIGN_KEY_CHECKS/d; /^[[:space:]]*(\/\*![0-9]+ )?SET /d; s/(INSERT INTO|LOCK TABLES|ALTER TABLE) \x60([A-Za-z0-9_]+)\x60/\1 '"$stage_db"'.\2/g' \
  | "${mysql_cmd[@]}" "$target_db"

for table in "${tables[@]}"; do
  count=$("${mysql_cmd[@]}" -e "SELECT COUNT(*) FROM $stage_db.$table;")
  printf '%s=%s\n' "$table" "$count"
done

echo "STAGING_PREPARATION=PASS"
