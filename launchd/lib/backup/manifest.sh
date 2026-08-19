# Sourced stage: manifest.
STAGE="manifest"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/nexus-backup.XXXXXX")" || die "cannot create a work directory"
cleanup_work() { [ -n "${WORK:-}" ] && rm -rf "$WORK"; }
MANIFEST="$WORK/manifest.txt"

{
  printf 'RCSL AI Nexus backup manifest\n'
  printf 'taken      %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf 'host       %s\n' "$(hostname -s)"
  printf 'repository %s\n' "$RESTIC_REPO"
  printf '\n'
  printf 'This file is stored unencrypted inside the encrypted repository. It\n'
  printf 'names what has to exist around a restore before the restore is worth\n'
  printf 'anything: the models to re-download, and the migration the dump was\n'
  printf 'taken at. Restoring a dump under a different schema head is the one\n'
  printf 'way this can fail silently, so that line is the one to read first.\n'
  printf '\n'
} > "$MANIFEST"

DB_META="$(docker compose exec -T postgres psql -U nexus -d nexus -tAc "
select 'alembic='||version_num from alembic_version
union all select 'model='||alias||'|'||ref||'|'||runtime||'|'||state||'|'||coalesce(observed_memory_gb::text,'-') from models
union all select 'policy='||capability||'|'||coalesce(thinking::text,'default') from routing_policies
" 2>/dev/null)"

if [ -z "$DB_META" ]; then
  die "could not read the manifest metadata out of Postgres; the container is running, so this is psql or the database itself"
fi

{
  printf 'Schema\n------\n'
  printf '%s\n' "$DB_META" | sed -n 's/^alembic=/  alembic head  /p'
  printf '\nModels registered (alias | runtime ref | runtime | intent | observed GB)\n'
  printf -- '----------------------------------------------------------------------\n'
  printf '%s\n' "$DB_META" | sed -n 's/^model=/  /p' | tr '|' '\t'
  printf '\nRouting policies (capability | thinking)\n'
  printf -- '---------------------------------------\n'
  printf '%s\n' "$DB_META" | sed -n 's/^policy=/  /p' | tr '|' '\t'
  printf '\nCompose services expected to be running\n'
  printf -- '--------------------------------------\n'
  printf '%s\n' "$RUNNING" | sed 's/^/  /'
} >> "$MANIFEST"

log "manifest built ($(wc -l < "$MANIFEST" | tr -d ' ') lines)"

if [ "$DRY_RUN" != "0" ]; then
  log "dry run: stopping before the first write. The manifest was:"
  cat "$MANIFEST"
  cleanup_work
  STAGE="done"
  exit 0
fi

# --- 1. the database --------------------------------------------------------
#
# Through `docker compose exec -T postgres pg_dump`, which needs no client on
# the host and no credential: the connection authenticates locally inside the
# container, the same reason check 14 of the health daemon needs none.
#
# Not gzipped, and that is deliberate. restic does content-defined chunking and
# compresses what it stores, so a compressed stream would defeat the
# deduplication that makes a nightly full dump cheap: two dumps a day apart
# differ in a few rows, and restic stores that difference — unless gzip has
# turned the whole file into different bytes from the first changed byte on.
#
# `--stdin-filename` is constant rather than dated, and that is load-bearing.
# `restic forget` groups snapshots by host and path, so a dated filename would
# put every snapshot in a group of one, every group would satisfy `keep-daily 7`
# on its own, and nothing would ever be pruned. The retention policy at the
# bottom would silently do nothing, which is a failure that looks exactly like
# success for about ninety days.
