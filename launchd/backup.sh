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
export DOCKER_HOST="unix:///Users/rcslmac1/.colima/default/docker.sock"
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

# Ordered stages; each is sourced so exit codes and shared state remain unchanged.
. "$REPO/launchd/lib/backup/state_watchdog.sh"
. "$REPO/launchd/lib/backup/preflight.sh"
. "$REPO/launchd/lib/backup/manifest.sh"
. "$REPO/launchd/lib/backup/postgres_dump.sh"
. "$REPO/launchd/lib/backup/documents.sh"
. "$REPO/launchd/lib/backup/secrets_manifest.sh"
. "$REPO/launchd/lib/backup/snapshot_retention.sh"
