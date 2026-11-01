#!/bin/sh
# Backs up the compose database the way the chart's CronJob does (pg_dump, custom
# format), restores it into a scratch database, and checks it: the same tables and row
# counts, and an intact audit chain. The scratch database is dropped afterwards.
#
#   scripts/backup-restore-check.sh
set -eu
cd "$(dirname "$0")/.."
psql_super() { docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres "$@"; }
dump=$(mktemp)
trap 'rm -f "$dump"; psql_super -d postgres -qc "DROP DATABASE IF EXISTS veyntora_restore_check" >/dev/null' EXIT

docker compose exec -T postgres pg_dump -U postgres --format=custom --no-owner veyntora > "$dump"
echo "dump: $(du -h "$dump" | cut -f1)"
psql_super -d postgres -qc "DROP DATABASE IF EXISTS veyntora_restore_check"
psql_super -d postgres -qc "CREATE DATABASE veyntora_restore_check"
docker compose exec -T postgres pg_restore -U postgres --no-owner -d veyntora_restore_check < "$dump"

tables="SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
src=$(psql_super -d veyntora -tAc "$tables")
dst=$(psql_super -d veyntora_restore_check -tAc "$tables")
echo "tables: $src → $dst"
[ "$src" = "$dst" ] || { echo "table count differs"; exit 1; }
for t in users chatbots documents audit_events conversations messages; do
  a=$(psql_super -d veyntora -tAc "SELECT count(*) FROM $t")
  b=$(psql_super -d veyntora_restore_check -tAc "SELECT count(*) FROM $t")
  echo "$t: $a → $b"
  [ "$a" = "$b" ] || { echo "rows of $t differ"; exit 1; }
done
chain=$(psql_super -d veyntora_restore_check -tAc "SELECT coalesce(audit_first_broken_link()::text, 'intact')")
echo "audit chain after restore: $chain"
[ "$chain" = "intact" ] || exit 1
echo "backup and restore: OK"
