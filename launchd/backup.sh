#!/bin/bash
# Take the encrypted backup, and be honest about what is not in it.
#
# Why this exists. security.md section 9.4 has described this backup since the
# first draft and nothing implemented it: until this file, a platform holding
# the team's unpublished research had no copy of it anywhere. The roadmap item
# is "encrypted backups and a rehearsed restore", and the rehearsal is the half
# that makes the other half worth anything — docs/runbooks/restore.md is the
# other half of this change and is not optional reading.
#
# What is in it, and what is deliberately not.
#
#   IN   the whole Postgres schema and its data, except `prompt_logs` rows
#   IN   the `documents` volume: uploaded files and their extracted text
#   IN   secrets/, without which the dump above cannot be used at all
#   IN   a plain-text manifest, readable without restoring anything
#   OUT  `prompt_logs` row data (the schema is kept; see below)
#   OUT  the Qdrant passage index, which is derived and is rebuilt on restore
#   OUT  redis-data, prometheus-data, grafana-data: sessions and metrics
#   OUT  model weights, which are re-downloadable; the manifest names them
#
# `prompt_logs` is excluded because section 9.4 offers two ways to bound it and
# only one of them is available here. The dataset carries a *ceiling* of 30 days
# on a default of 7 (domain/entities/retention.py), precisely so this platform
# does not accumulate a corpus of unpublished ideas; the two ways out are to
# exclude the table or to keep the backups for less time than the dataset does,
# and a backup retention under seven days is not a backup. So: excluded. The
# argument that settles it is cheaper than that one, though — the rows have no
# recovery value. A prompt transcript exists for the length of a debugging
# session, and nobody restoring from a disaster wants a three-week-old debug
# transcript. This is the unusual case where the safe choice and the free choice
# are the same choice.
#
# It is `--exclude-table-data` and not `--exclude-table` on purpose. Dropping
# the table would restore a database missing a table `RouteChatRequest` writes
# to, so the first request after a restore would fail on a platform that
# reported a successful restore. The schema survives; the rows do not.
#
# `refusals` is kept, and the retention below is what bounds it. It is the same
# interaction one notch weaker: it holds no request content, only codes,
# statuses and the message the caller received, so it is not the section 9.2
# hazard — but its own 180-day ceiling exists because a long enough history of
# somebody's refusals describes how they work. The retention policy at the
# bottom of this file keeps roughly 90 days, which is section 9.4's *other*
# option taken explicitly: backup retention shorter than the dataset's.
#
# secrets/ is in the repository, and that is the largest decision in this file.
# Leaving it out produces something that is not a restore: `totp_encryption_key`
# is what every stored TOTP secret is encrypted under, and `api_key_pepper` is
# what every API key hash is peppered with. Without those two files the restored
# database is one where every administrator is locked out and every key is dead.
# So the question was never safe-versus-unsafe, it was one item kept off this
# machine or sixteen — and one is the number that will still be correct in a
# year. What it costs, said plainly: the restic repository password plus read
# access to the repository is the entire platform. That concentration is exactly
# why the password must not live only on the machine being backed up, and it is
# the one step in restore.md that nothing here can verify for you.
#
# The Qdrant index is out because it is derived, and because taking it properly
# means a third clock. A consistent copy needs the snapshot API and the API key,
# at a moment that relates to neither of the two captures below; and
# adapters/vector/qdrant_store.py derives point ids rather than generating them,
# which is what makes a re-index idempotent. So the restore rebuilds it. That
# cost is not zero — it is every document embedded again — and restore.md
# carries the loop rather than leaving it as an exercise.
#
# THE TWO CAPTURES ARE NOT ATOMIC WITH RESPECT TO EACH OTHER, and no ordering
# fixes that. `knowledge_documents` rows point at files in the `documents`
# volume, so between the dump and the tar the two can disagree in two ways:
# a document uploaded in the window leaves a file with no row (an orphan file,
# invisible and harmless), and a document deleted in the window leaves a row
# with no file (a document that lists, opens and fails). Uploads and deletes cut
# opposite ways, so an ordering can only choose which of the two it prefers.
# The dump goes first because uploads are ordinary and deletes are rare, which
# makes the harmless shape the common one. The remaining shape is not papered
# over: restore.md ends with a reconciliation query that lists exactly the rows
# whose file did not come back, so a rare inconsistency arrives as a named list
# rather than as a document that mysteriously 500s six months later. Making the
# window truly atomic means stopping the stack nightly, and a platform that
# stops serving every night to protect data it is not serving is a worse trade.
#
# Note also that the live database already produces that shape transiently:
# `ManageKnowledge._forget_document` deletes the bytes before the row, on
# purpose, so that a half-finished delete leaves something the operator can see
# and retry.
#
# Written for the bash 3.2 that macOS ships: no mapfile, no associative arrays.
# `/usr/bin/python3` is stdlib-only and never a virtualenv, for the reason
# online.rcsl.host-metrics.plist gives: a launchd job that depends on a project
# venv breaks the first time the project is rebuilt.
#
# This script never sends mail. The health daemon reads the state file it writes
# and reports from there (check-platform-health.sh check 15), which keeps one
# mailer on this machine rather than two, and means a backup that hangs is
# reported by the thing already watching rather than by nothing at all.

set -uo pipefail

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
export DOCKER_HOST="unix:///Users/rcslmac1/.docker/run/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Where the backup goes. A reviewable constant rather than an untracked file,
# for the same reason ALERT_TO is one in check-platform-health.sh: a change to
# it should show up in a diff.
#
# This is one repository, which is one leg of the 3-2-1 section 9.4 asks for.
# The second leg is offsite, and it is not written here because it is blocked on
# a question this end cannot answer: whether institutional policy and the
# collaboration agreements permit unpublished research data on third-party cloud
# storage. Until somebody answers that, claiming 3-2-1 would be the kind of
# marked-done-but-not-in-force control this repository has already found eight
# of. Adding the second leg later is a second repository and a second `restic`
# call, not a rewrite.
# **TEMPORARY, AND IT IS NOT A BACKUP AGAINST THE DISK FAILING.** This machine
# had no external disk on 2026-08-18 — `diskutil list external` was empty — so
# the repository shares a device with the data it is copying. What that still
# defends against is real and worth having: a bad migration, a mistaken
# `docker volume rm`, a deleted collection, a table truncated by hand. What it
# does not defend against is the one thing a backup is usually bought for. It
# is here because the alternative was to leave the whole mechanism unverified
# until a disk arrives, and an unrehearsed backup is the failure this project
# has already recorded eight of.
#
# Moving it is two lines: point both constants at the external volume
# (`/Volumes/nexus-backup/restic` and `/Volumes/nexus-backup`) and run
# `restic init` there once. Nothing else in this file changes.
#
# `/Users/Shared` rather than the operator's home directory, for the reason the
# Ollama service account move found on 2026-08-18: a 750 home directory is why
# that had never moved, and a daemon should not depend on one person's
# permissions.
RESTIC_REPO="/Users/Shared/nexus-backup/restic"

# The mount the repository lives on. Checked separately from the repository
# path, because an unmounted external disk on macOS leaves an ordinary empty
# directory at its mount point: without this check a nightly backup would
# quietly build a second, complete, growing repository on the boot volume while
# the real one sat untouched on a disk nobody had plugged in, and every run
# would report success. That is the confident-wrong-answer failure this
# repository keeps rediscovering, so it gets its own check and its own message.
#
# **In the temporary configuration above this check cannot bite**, because the
# boot volume is where the repository is meant to be, and saying so is better
# than deleting the check and rediscovering why it was written. It re-arms by
# itself the moment `RESTIC_REPO_MOUNT` names a real external volume again.
RESTIC_REPO_MOUNT="/"

RESTIC_PASSWORD_FILE="$REPO/secrets/restic_password"
export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD_FILE

# Daily for a week covers the ordinary "yesterday was fine" restore; weekly and
# monthly cover a corruption noticed late.
#
# **What this actually retains was measured rather than assumed, and the first
# figure written here was wrong.** It said "roughly ninety days". Against 130
# synthetic daily snapshots on 2026-08-18 the policy kept 11 and spanned **49
# days**, because the monthly leg counts calendar months rather than 30-day
# windows: three months on the 18th reaches back to the last snapshot of June.
# The span therefore oscillates through the month, from about 32 days on the
# first to about 92 on the last. What has to be true is that the *ceiling* of
# that range stays under the 180 days `refusals` carries, which is what lets
# that table be in the backup at all (see the header), and 92 does — with more
# margin than the sentence it replaces claimed.
#
# Measured at the same time: restic 0.19 pins the oldest snapshot of each group
# with the reason `oldest daily snapshot`, so two runs on the same day both
# survive a forget. That is why the second test run did not collapse into the
# first. It pins only within what the policy already keeps — the 130-snapshot
# run proves it prunes the rest — so it costs one extra snapshot, not a
# retention window that never ends.
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=3

# The state file is also the liveness record: its mtime is the last run, and
# check 15 of the health daemon reads it as one. Three lines, and every path
# that writes it writes all three:
#   1  the last SUCCESSFUL completion, ISO-8601 with offset, empty if never
#   2  the outcome of the LAST run: `ok`, or `failed:<stage>`
#   3  figures for the digest: "<db-bytes> <documents-bytes> <repo-snapshots>"
# Lines 1 and 2 are separate on purpose. A run that fails must not erase the
# fact that Tuesday's backup exists, and a run that succeeds must not hide that
# the three before it did not.
STATE_FILE="/opt/homebrew/var/nexus-backup.state"

# The whole run gets a deadline. launchd will not start a second instance of a
# StartCalendarInterval job while the first is still running, so one hang would
# stop every future backup — and unlike the health daemon, nothing about this
# job is noticed by its own absence. Two hours is far above the minutes this
# takes and far below the day until the next fire.
MAX_RUN_SECONDS=7200

# `NEXUS_BACKUP_DRY_RUN=1 bash backup.sh` runs every preflight check, builds the
# manifest, and stops before the first byte is written to the repository. It
# writes no state, for the same reason the health daemon's dry run does not: a
# dry run that recorded a success would make the next real failure invisible.
DRY_RUN="${NEXUS_BACKUP_DRY_RUN:-0}"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

STAGE="startup"
RC=0

PREV_SUCCESS=""
if [ -f "$STATE_FILE" ]; then
  PREV_SUCCESS="$(sed -n '1p' "$STATE_FILE" 2>/dev/null)"
fi

write_state() {
  # $1 last successful completion (or empty), $2 outcome, $3 figures
  [ "$DRY_RUN" != "0" ] && return 0
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  printf '%s\n%s\n%s\n' "$1" "$2" "$3" > "$STATE_FILE"
}

# Any exit that is not the happy path still has to leave the state file saying
# what stage it died in, including a kill from the watchdog below. Without this
# a hung run leaves yesterday's `ok` in place and the freshness check reads a
# stale success as a current one.
FIGURES="- - -"
on_exit() {
  local code=$?
  if [ "$STAGE" != "done" ]; then
    write_state "$PREV_SUCCESS" "failed:$STAGE" "$FIGURES"
    log "ERROR: exiting at stage '$STAGE' with code $code; last success was ${PREV_SUCCESS:-<never>}"
  fi
  exit $code
}
trap on_exit EXIT
trap 'exit 143' TERM INT

# The watchdog polls instead of sleeping once, and both halves of that are
# repairs to the obvious version. The obvious version is
# `( sleep "$MAX_RUN_SECONDS"; kill -TERM $$ ) &` with a `kill` in the exit
# trap, and it is wrong twice.
#
# It inherits this script's stdout, so the pipe stays open after the script has
# exited: `bash backup.sh | tail` hangs for two hours against a script that
# finished in seconds. Found on 2026-08-18 by running exactly that. Under
# launchd stdout is a file, so this would never have shown up there — it would
# have shown up as a `sleep 7200` process left behind by every nightly run.
#
# And the `kill` in the trap does not do what it reads as. `$!` is the
# subshell's pid; `sleep` is its child, so killing the subshell orphans the
# sleep rather than ending it. Two of them were still running when this was
# found.
#
# So: no kill, and nothing to get wrong. `$$` is not rewritten inside a
# subshell, so `kill -0 $$` asks whether this script is still alive; when it is
# not, the loop ends by itself within one poll. The residue after any exit is at
# most a 30-second sleep, and the deadline is still enforced to the same
# precision that matters for a two-hour ceiling.
START_EPOCH="$(date +%s)"
( while kill -0 $$ 2>/dev/null; do
    sleep 30
    if [ $(( $(date +%s) - START_EPOCH )) -gt "$MAX_RUN_SECONDS" ]; then
      kill -TERM $$ 2>/dev/null
      exit 0
    fi
  done ) >/dev/null 2>&1 &

die() { log "ERROR: $*"; exit 1; }

# --- preflight --------------------------------------------------------------
#
# Every one of these can fail in a way that produces a *successful-looking*
# backup, which is why they are checks and not assumptions.

STAGE="preflight"
cd "$REPO" || die "cannot enter $REPO"

command -v restic >/dev/null 2>&1 || \
  die "restic is not on PATH; install it with \`brew install restic\` (see docs/runbooks/restore.md)"

[ -f "$RESTIC_PASSWORD_FILE" ] || \
  die "$RESTIC_PASSWORD_FILE is missing; see secrets/README.md"

[ -d "$RESTIC_REPO_MOUNT" ] || \
  die "$RESTIC_REPO_MOUNT does not exist; the backup disk is not mounted"

# An empty directory at the mount point is what an unmounted disk looks like.
# `mount` naming it is what a mounted one looks like.
if ! /sbin/mount | grep -q " on $RESTIC_REPO_MOUNT "; then
  die "$RESTIC_REPO_MOUNT exists but nothing is mounted there; refusing to write a second repository onto the boot volume"
fi

# Deliberately not `restic init`. A typo in RESTIC_REPO, or a disk that mounted
# at a slightly different path, would otherwise create a fresh empty repository
# and every subsequent run would succeed against it while the real history sat
# somewhere else. Initialising is a one-time operator step, and restore.md says
# so.
if ! restic cat config >/dev/null 2>&1; then
  die "no restic repository at $RESTIC_REPO (or the password is wrong); initialise it once by hand — see docs/runbooks/restore.md section 1"
fi

docker compose version >/dev/null 2>&1 || die "the docker daemon is not answering"

RUNNING="$(docker compose ps --services --filter status=running 2>/dev/null)"
printf '%s\n' "$RUNNING" | grep -qx postgres || \
  die "the postgres service is not running; there is nothing to dump"

ADMIN_SERVICE=""
for candidate in admin-tailnet admin-public; do
  if printf '%s\n' "$RUNNING" | grep -qx "$candidate"; then ADMIN_SERVICE="$candidate"; break; fi
done
[ -n "$ADMIN_SERVICE" ] || \
  die "neither admin entrance is running; the documents volume is only reachable through a container that mounts it"

ADMIN_CONTAINER="$(docker compose ps -q "$ADMIN_SERVICE" 2>/dev/null)"
[ -n "$ADMIN_CONTAINER" ] || die "could not resolve a container id for $ADMIN_SERVICE"

log "preflight ok: repo $RESTIC_REPO, documents via $ADMIN_SERVICE"

# --- the manifest -----------------------------------------------------------
#
# Section 9.4 asks for a manifest of models and versions so the environment can
# be reconstructed. It is written as plain text and stored as a file rather than
# left implicit in the dump, because the situation it is for is the one where
# nothing has been restored yet: an operator standing in front of a new machine
# needs to know which weights to pull before a database exists to read it from.

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

STAGE="database"
log "dumping the database"
if ! docker compose exec -T postgres pg_dump -U nexus -d nexus \
      --format=plain --no-owner --no-privileges \
      --exclude-table-data=prompt_logs \
    | restic backup --stdin --stdin-filename nexus.sql \
        --tag database --tag "$(date '+%Y-%m-%d')" ; then
  die "the database dump did not reach the repository"
fi

# --- 2. the documents volume ------------------------------------------------
#
# `docker cp` rather than `tar` inside the container, because `docker cp`
# streams a tar of the path to stdout using the daemon's own copy machinery and
# therefore depends on nothing being installed in the image. A `tar` that the
# backend image happens to ship today is a dependency nobody would think to
# check when the base image changes.
#
# The volume is only reachable through a container: on macOS, Docker volumes
# live inside the Linux VM and have no path on the host filesystem, so there is
# nothing here for restic to walk.

STAGE="documents"
log "capturing the documents volume through $ADMIN_SERVICE"
if ! docker cp "$ADMIN_CONTAINER:/var/lib/nexus/documents/." - \
    | restic backup --stdin --stdin-filename documents.tar \
        --tag documents --tag "$(date '+%Y-%m-%d')" ; then
  die "the documents volume did not reach the repository"
fi

# --- 3. the secrets and the manifest ----------------------------------------
#
# Ordinary files on the host, so these go in as paths rather than as streams and
# restic deduplicates them properly. `secrets/*.example` and the README are
# tracked in git and are excluded here: they are not credentials and restoring
# them from a backup instead of from the repository is how a placeholder ends up
# in production.

STAGE="secrets"
log "capturing secrets"
if ! restic backup "$REPO/secrets" \
      --exclude '*.example' --exclude 'README.md' \
      --tag secrets --tag "$(date '+%Y-%m-%d')" ; then
  die "secrets did not reach the repository"
fi

# The manifest goes in as its own stdin snapshot rather than as a second path on
# the call above, and the reason is the same grouping rule the database capture
# explains: it is built in a `mktemp -d` directory whose name is different every
# run, so as a path it would put every night's snapshot in a group of one, and
# `restic forget` would keep all of them forever. As `/manifest.txt` it has one
# stable path, one group, and a name the runbook can quote.

STAGE="manifest-store"
if ! restic backup --stdin --stdin-filename manifest.txt \
      --tag manifest --tag "$(date '+%Y-%m-%d')" < "$MANIFEST" ; then
  die "the manifest did not reach the repository"
fi

# --- 4. retention -----------------------------------------------------------
#
# `--prune` in the same call, because a `forget` without one removes the
# snapshot and leaves every byte it referenced on the disk: the repository would
# grow forever while reporting the right number of snapshots, and the retention
# decision at the top of this file — the one that lets `refusals` be in the
# backup at all — would be true of the listing and false of the data.

STAGE="retention"
log "applying retention: ${KEEP_DAILY}d ${KEEP_WEEKLY}w ${KEEP_MONTHLY}m"
if ! restic forget --prune \
      --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" ; then
  die "retention failed; the repository may be holding more than the policy says"
fi

# --- 5. does the repository still make sense --------------------------------
#
# Structure only: `restic check` without `--read-data` verifies that every
# snapshot's metadata resolves and that no pack is missing from the index. It
# does not read the data back, so it cannot detect a silently corrupted pack.
# Reading everything back is what the rehearsed restore is for, and that is a
# person with a runbook rather than a nightly job — see restore.md section 4.
# Saying which of the two this is matters, because "check passed" is exactly the
# sentence somebody will later remember as "the backup was verified".

STAGE="verify"
if ! restic check ; then
  die "the repository failed its structural check"
fi

# --- 6. figures and state ---------------------------------------------------

STAGE="state"
SNAP_COUNT="$(restic snapshots --json 2>/dev/null | /usr/bin/python3 -c '
import json,sys
try: print(len(json.load(sys.stdin)))
except Exception: print("-")
')"
REPO_BYTES="$(restic stats --mode raw-data --json 2>/dev/null | /usr/bin/python3 -c '
import json,sys
try: print(json.load(sys.stdin).get("total_size","-"))
except Exception: print("-")
')"
FIGURES="${SNAP_COUNT:--} ${REPO_BYTES:--} $RESTIC_REPO"

NOW="$(date '+%Y-%m-%dT%H:%M:%S%z')"
write_state "$NOW" "ok" "$FIGURES"
cleanup_work
STAGE="done"
log "backup complete: $SNAP_COUNT snapshots, $REPO_BYTES bytes of raw data in $RESTIC_REPO"
exit $RC
