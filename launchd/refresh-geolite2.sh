#!/bin/bash
# Keep the GeoLite2 country database current.
#
# Why this exists. The database was dropped into ./data once at the first
# deploy and nothing since has said it needs updating. MaxMind publishes
# twice weekly and IP ranges move between countries, so a static copy
# misclassifies more as it ages — silently, and in both directions: callers
# from allowed countries refused, callers from refused countries admitted.
# MaxMind's own licence also expects the data to be kept current (and to be
# deleted if the licence ends), so refreshing is a term of use, not a
# preference. ROADMAP.md Phase 3 carried this; docs/PROGRESS.md 2026-07-26
# recorded that nothing said so before that day.
#
# The credential is the account's permanent licence key, read from
# secrets/maxmind_license_key — unlike the throwaway API tokens used during
# the first setup, this one is long-lived, which is the property a scheduled
# job needs. The legacy download endpoint takes the key alone; the newer
# permalinks need the account id as well, for no benefit here.
#
# A swap is not enough on its own: geoip2 opens the file once at startup
# (interfaces/http/middleware/geo_filter.py), so the two containers that
# enforce the country filter are restarted when — and only when — the file
# actually changed. MaxMind publishes twice a week, so most runs change
# nothing and restart nothing. The restart is `docker compose restart`, which
# on these services is safe precisely because it reuses the container: no
# port binding is recreated, so the boot-time binding race this repo's
# reconciler exists for cannot be re-entered from here.
#
# Failure leaves the old database in place and serving, which is the correct
# degraded state: stale beats absent (build_geo_filter refuses to start
# without the file in production). The health-check daemon does not watch
# this; a failure is a non-zero exit in this log, and the STALENESS check at
# the top turns a quietly-broken refresh into a loud one eventually.
#
# Written for the bash 3.2 that macOS ships.

set -uo pipefail

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
export DOCKER_HOST="unix:///Users/rcslmac1/.colima/default/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

EDITION="GeoLite2-Country"
TARGET="$REPO/data/GeoLite2-Country.mmdb"
KEY_FILE="$REPO/secrets/maxmind_license_key"
# The services whose geo filter actually refuses requests: the gateway and the
# public admin entrance (security.md §4.1). The tailnet entrance sits behind
# the tailnet and is deliberately not cycled for this.
ENFORCING_SERVICES="gateway admin-public"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

log "geolite2 refresh starting"

# Complain while the database still works, not after it has quietly rotted:
# if the file is over 30 days old the refreshes have been failing for a
# month, and this line is what makes that visible even to someone reading
# only the latest run.
if [ -f "$TARGET" ]; then
  AGE_DAYS=$(( ( $(date +%s) - $(stat -f %m "$TARGET") ) / 86400 ))
  [ "$AGE_DAYS" -gt 30 ] && log "WARNING: current database is ${AGE_DAYS} days old; refreshes have been failing"
fi

if [ ! -s "$KEY_FILE" ]; then
  log "FATAL: no licence key at $KEY_FILE; see secrets/README.md"
  exit 1
fi
LICENSE_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"

# Beside the target, not in /tmp, and that is what makes the `mv` below atomic:
# `mv` is a rename only within one filesystem, and degrades to copy-then-unlink
# across two — which is exactly the half-written file a reader must never see.
# /tmp and the repository happen to share a volume on this host today; a repo on
# an external disk would silently turn the swap into a copy. Cleaned up by the
# trap either way, and ./data is gitignored.
WORK="$(mktemp -d "$REPO/data/.geolite2.XXXXXX")" || { log "FATAL: mktemp failed"; exit 1; }
trap 'rm -rf "$WORK"' EXIT

# --fail turns MaxMind's 401 (bad key) into a non-zero exit instead of an HTML
# body being handed to tar. The URL never carries the key into this log.
if ! curl --fail --silent --show-error --location --max-time 300 \
    --output "$WORK/db.tar.gz" \
    "https://download.maxmind.com/app/geoip_download?edition_id=${EDITION}&license_key=${LICENSE_KEY}&suffix=tar.gz" 2>&1; then
  log "FATAL: download failed; the current database stays in place"
  exit 1
fi

if ! tar -xzf "$WORK/db.tar.gz" -C "$WORK" 2>&1; then
  log "FATAL: archive would not extract; the current database stays in place"
  exit 1
fi

NEW="$(find "$WORK" -name '*.mmdb' -type f | head -1)"
if [ -z "$NEW" ]; then
  log "FATAL: archive contained no .mmdb; the current database stays in place"
  exit 1
fi

# Two checks that cost nothing and each catch a different corruption: the mmdb
# metadata marker proves the format, the size floor catches a truncated body
# that happens to keep the marker. The real file is ~9 MB.
if ! grep -q "MaxMind.com" "$NEW" || [ "$(stat -f %z "$NEW")" -lt 1000000 ]; then
  log "FATAL: downloaded file does not look like a GeoLite2 database; keeping the current one"
  exit 1
fi

if [ -f "$TARGET" ] && cmp -s "$NEW" "$TARGET"; then
  log "database unchanged upstream; nothing to do"
  exit 0
fi

# A rename within ./data, so it is atomic and no reader can see a half-written
# file — see the mktemp above for why the work directory has to live there. The
# container mounts the directory, not the file, which is what lets a replaced
# inode be visible on the next open.
if ! mv "$NEW" "$TARGET"; then
  log "FATAL: could not replace $TARGET"
  exit 1
fi
log "database replaced"

cd "$REPO" || { log "FATAL: cannot cd to $REPO"; exit 1; }
if ! docker info >/dev/null 2>&1; then
  log "WARNING: docker not responding; new database takes effect at the next restart"
  exit 1
fi

# Restart, never recreate: see the header. Word-splitting is intentional.
if docker compose restart $ENFORCING_SERVICES 2>&1; then
  log "OK: refreshed and restarted: $ENFORCING_SERVICES"
else
  log "WARNING: restart returned non-zero; the containers may be serving the old data until restarted"
  exit 1
fi
