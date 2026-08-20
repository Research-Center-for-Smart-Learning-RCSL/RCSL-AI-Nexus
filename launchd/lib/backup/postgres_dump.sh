# Sourced stage: postgres dump.
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
