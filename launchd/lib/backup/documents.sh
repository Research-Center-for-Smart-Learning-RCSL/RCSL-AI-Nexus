# Sourced stage: documents.
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
