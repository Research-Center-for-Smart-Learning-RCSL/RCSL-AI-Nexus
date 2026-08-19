# Sourced stage: preflight.
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
