#!/bin/sh
#
# Move Ollama off the operator's login and onto a dedicated non-administrator
# service account, which is what security.md 7.1(d) has described since it was
# written and what nothing did until 2026-08-18.
#
# **Why this needs a script rather than a paragraph.** The change is five
# things that have to happen together — an account, a directory move, its
# ownership, the log it writes to, and the plist — and any one of them alone
# leaves the daemon unable to start. A daemon that cannot start on a machine
# whose whole purpose is inference is a worse outcome than the risk being
# closed, so every step below refuses rather than guesses, and the rollback is
# printed before anything is touched.
#
# **What it costs while it runs.** Inference is down from the bootout to the
# bootstrap, which is seconds, plus the first request afterwards paying a cold
# load of whatever was resident. Nothing else on the platform stops: the
# gateway answers 503 `no_available_model` for that window rather than hanging.
#
# **The directory move is a rename, not a copy.** /Users/Shared and
# /Users/rcslmac1 are on the same volume (verified: both /dev/disk3s5), so the
# 214 GB in there moves instantly. If that ever stops being true this script
# will take minutes rather than a second, and the bootout above it means those
# minutes are downtime.
#
# Usage:  sudo sh launchd/adopt-ollama-service-account.sh
#         sudo sh launchd/adopt-ollama-service-account.sh --rollback
#
set -eu

SERVICE_USER="_rcslollama"
SERVICE_GROUP="_rcslollama"
SERVICE_ID=470
REAL_NAME="RCSL Ollama Runtime"

OPERATOR_HOME="/Users/rcslmac1/.ollama"
SERVICE_HOME="/Users/Shared/ollama"

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
PLIST_SRC="$REPO/launchd/online.rcsl.ollama.plist"
PLIST_DST="/Library/LaunchDaemons/online.rcsl.ollama.plist"
LABEL="online.rcsl.ollama"
LOG="/opt/homebrew/var/log/ollama.log"
API="http://127.0.0.1:11434/api/tags"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
refuse() { log "REFUSING: $1"; log "nothing was changed"; exit 1; }

[ "$(id -u)" = "0" ] || refuse "run this with sudo"

# --- rollback ---------------------------------------------------------------
#
# Deliberately first in the file. Whoever needs it is not reading from the top.

if [ "${1:-}" = "--rollback" ]; then
  log "rolling back to the operator's login"
  launchctl bootout "system/$LABEL" 2>/dev/null || true
  sleep 2
  if [ -d "$SERVICE_HOME" ] && [ ! -d "$OPERATOR_HOME" ]; then
    mv "$SERVICE_HOME" "$OPERATOR_HOME"
    chown -R rcslmac1:staff "$OPERATOR_HOME"
  fi
  chown rcslmac1:admin "$LOG" 2>/dev/null || true
  # The plist in the repository is the new one; git is where the old one is.
  log "now restore the plist and load it:"
  log "  cd $REPO && git show HEAD~1:launchd/online.rcsl.ollama.plist > /tmp/ollama.plist"
  log "  sudo cp /tmp/ollama.plist $PLIST_DST && sudo launchctl bootstrap system $PLIST_DST"
  log "and put OLLAMA_MODELS_HOST_PATH back to $OPERATOR_HOME/models in .env,"
  log "then: docker compose up -d --force-recreate gateway admin-tailnet admin-public"
  exit 0
fi

# --- refuse unless the world is the one this was written for ----------------

[ -f "$PLIST_SRC" ] || refuse "$PLIST_SRC is missing; run this from a checkout"
grep -q "$SERVICE_USER" "$PLIST_SRC" || refuse "$PLIST_SRC does not name $SERVICE_USER; it is the old plist"

if [ -d "$SERVICE_HOME" ]; then
  refuse "$SERVICE_HOME already exists. Either this has already run, or something
  else owns that path. Check it by hand rather than letting this merge two trees."
fi

[ -d "$OPERATOR_HOME" ] || refuse "$OPERATOR_HOME does not exist; nothing to move"
[ -d "$OPERATOR_HOME/models" ] || refuse "$OPERATOR_HOME/models does not exist; this is not an ollama home"

if dscl . -read "/Users/$SERVICE_USER" >/dev/null 2>&1; then
  refuse "$SERVICE_USER already exists. Remove it first, or edit SERVICE_USER here."
fi

taken="$(dscl . -search /Users UniqueID "$SERVICE_ID" 2>/dev/null | head -1)"
[ -z "$taken" ] || refuse "uid $SERVICE_ID is taken by: $taken"
taken="$(dscl . -search /Groups PrimaryGroupID "$SERVICE_ID" 2>/dev/null | head -1)"
[ -z "$taken" ] || refuse "gid $SERVICE_ID is taken by: $taken"

# Same volume, or the move below is a 214 GB copy inside a service outage.
src_vol="$(df -P "$OPERATOR_HOME" | awk 'NR==2 {print $1}')"
dst_vol="$(df -P /Users/Shared | awk 'NR==2 {print $1}')"
[ "$src_vol" = "$dst_vol" ] || refuse "$OPERATOR_HOME ($src_vol) and /Users/Shared ($dst_vol)
  are on different volumes, so the move is a copy of 214 GB with inference down
  for the whole of it. Do this during a window you have chosen, not this script's."

log "pre-flight passed"
log "rollback if anything goes wrong: sudo sh $0 --rollback"

# --- the account ------------------------------------------------------------
#
# Not in `admin`, no login shell, hidden from the login window. A daemon
# account that can open a session is a daemon account that can be used as one.

log "creating group $SERVICE_GROUP ($SERVICE_ID)"
dscl . -create "/Groups/$SERVICE_GROUP"
dscl . -create "/Groups/$SERVICE_GROUP" PrimaryGroupID "$SERVICE_ID"
dscl . -create "/Groups/$SERVICE_GROUP" RealName "$REAL_NAME"

log "creating user $SERVICE_USER ($SERVICE_ID)"
dscl . -create "/Users/$SERVICE_USER"
dscl . -create "/Users/$SERVICE_USER" UniqueID "$SERVICE_ID"
dscl . -create "/Users/$SERVICE_USER" PrimaryGroupID "$SERVICE_ID"
dscl . -create "/Users/$SERVICE_USER" RealName "$REAL_NAME"
dscl . -create "/Users/$SERVICE_USER" UserShell /usr/bin/false
dscl . -create "/Users/$SERVICE_USER" NFSHomeDirectory "$SERVICE_HOME"
dscl . -create "/Users/$SERVICE_USER" IsHidden 1
dscl . -create "/Users/$SERVICE_USER" Password '*'

# --- stop, move, own --------------------------------------------------------

log "stopping $LABEL"
launchctl bootout "system/$LABEL" 2>/dev/null || log "  (was not loaded)"

waited=0
while pgrep -f 'ollama serve' >/dev/null 2>&1; do
  waited=$((waited + 1))
  [ "$waited" -gt 30 ] && refuse "ollama is still running 30s after bootout; stop it by hand"
  sleep 1
done
log "  stopped after ${waited}s"

log "moving $OPERATOR_HOME -> $SERVICE_HOME"
mv "$OPERATOR_HOME" "$SERVICE_HOME"

# Group `staff`, not the service group: Docker Desktop shares this path as the
# operator, and the gateway bind-mounts it read-only for the tokenizer. Owner
# rwx, group r-x, everyone else nothing.
log "owning it to $SERVICE_USER:staff"
chown -R "$SERVICE_USER:staff" "$SERVICE_HOME"
chmod -R u+rwX,g+rX,o-rwx "$SERVICE_HOME"

# The daemon's stdout. Owned by the operator until now, and a daemon that
# cannot open its own log does not start.
log "owning $LOG"
[ -f "$LOG" ] || touch "$LOG"
chown "$SERVICE_USER:admin" "$LOG"
chmod 644 "$LOG"

# --- the plist --------------------------------------------------------------

log "installing $PLIST_DST"
cp "$PLIST_SRC" "$PLIST_DST"
chown root:wheel "$PLIST_DST"
chmod 644 "$PLIST_DST"
plutil -lint "$PLIST_DST" >/dev/null || refuse "the installed plist does not parse"

log "starting $LABEL"
launchctl bootstrap system "$PLIST_DST"

# --- verify -----------------------------------------------------------------

waited=0
until curl -fsS --max-time 3 "$API" >/dev/null 2>&1; do
  waited=$((waited + 1))
  if [ "$waited" -gt 60 ]; then
    log "FAILED: ollama did not answer $API within 60s"
    log "look at $LOG, then: sudo sh $0 --rollback"
    exit 1
  fi
  sleep 1
done
log "ollama answered after ${waited}s"

running_as="$(ps -axo user,command | awk '/[o]llama serve/ {print $1; exit}')"
[ "$running_as" = "$SERVICE_USER" ] || log "WARNING: running as '$running_as', expected $SERVICE_USER"
log "running as: $running_as"

models="$(curl -fsS "$API" | grep -o '"name":"[^"]*"' | wc -l | tr -d ' ')"
log "models visible through the API: $models"
[ "$models" -gt 0 ] || log "WARNING: the API lists no models; check OLLAMA_MODELS in the plist"

log "done. Still to do, and not by this script:"
log "  1. .env  OLLAMA_MODELS_HOST_PATH=$SERVICE_HOME/models"
log "  2. docker compose up -d --force-recreate gateway admin-tailnet admin-public"
log "  3. confirm the tokenizer still sees the weights, in both containers that"
log "     count with it -- the mount was missing from the admin entrances until"
log "     2026-08-18 and nothing failed when it was:"
log "     docker exec rcsl-ai-nexus-gateway-1 ls /ollama-models/blobs | head -3"
log "     docker exec rcsl-ai-nexus-admin-tailnet-1 ls /ollama-models/blobs | head -3"
log "  4. warm every model the registry calls loaded. Restarting the runtime"
log "     evicted all of them: chat and code come back on their own, because"
log "     an inference request loads what it needs, but embedding cannot --"
log "     routing requires an OBSERVED loaded and nothing on that path loads"
log "     on demand, so the capability stays down until somebody warms it and"
log "     nothing announces that it is down. Admin UI, Models, Load; or POST"
log "     /api/embed with keep_alive -1 and an empty input. One heartbeat"
log "     (30s) later models.observed_state should read loaded. Missed on"
log "     2026-08-18, and the embedder was down for two hours"
