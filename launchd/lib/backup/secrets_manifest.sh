# Sourced stage: secrets manifest.
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
