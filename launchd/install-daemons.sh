#!/bin/bash
# Render the LaunchDaemon templates in this directory, check them against what
# is installed, and install them.
#
# The plists here are templates because the repository is public: the account
# a job runs as and the checkout it runs from are this host's, not the code's.
# `@OPERATOR@` is the operator's account and `@REPO@` the checkout's absolute
# path. A plist with neither installs as it is.
#
#   launchd/install-daemons.sh --check                 # no sudo; exit 1 on drift
#   sudo launchd/install-daemons.sh LABEL...           # install, do not reload
#   sudo launchd/install-daemons.sh --installed        # every one already installed
#   sudo launchd/install-daemons.sh --reload LABEL     # install LABEL, then bootout and bootstrap it
#
# LABEL is the file's label, `online.rcsl.backup` or just `backup`.
#
# **Installing never restarts a job unless `--reload` names it.** launchd reads
# a plist when the job is bootstrapped, so a copied file changes nothing until
# then; reloading a KeepAlive job stops what it runs (`colima` stops the VM and
# every container). `--installed` exists because a bare "all" would also
# install `delay-tailscaled-once`, a fault-injection tool that must never be
# left installed.
#
# `--check` compares content, not bytes: plutil's JSON of the rendered file
# against the installed one's. Comment-only drift is reported but is not a
# failure, because launchd never reads comments.
#
# Written for the bash 3.2 that macOS ships.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
REPO="$(cd "$HERE/.." && pwd -P)"
DEST="/Library/LaunchDaemons"
OPERATOR=""
MODE="install"
INSTALLED_ONLY=0
RELOAD=""
LABELS=""

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
die() { printf 'install-daemons: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --installed) INSTALLED_ONLY=1 ;;
    --operator) shift; OPERATOR="${1:-}" ;;
    --repo) shift; REPO="${1:-}" ;;
    --reload) shift; RELOAD="$RELOAD ${1:-}"; LABELS="$LABELS ${1:-}" ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) LABELS="$LABELS $1" ;;
  esac
  shift
done

# The account defaults to whoever ran sudo, then to the checkout's owner.
[ -n "$OPERATOR" ] || OPERATOR="${SUDO_USER:-}"
[ -n "$OPERATOR" ] || OPERATOR="$(/usr/bin/stat -f %Su "$REPO")"

# Substituted into XML with sed, so refuse anything that is not a plain account
# name and a plain absolute path rather than escape it.
case "$OPERATOR" in
  ""|root|*[!A-Za-z0-9_.-]*) die "operator '$OPERATOR' is not a plain account name" ;;
esac
case "$REPO" in
  /*) ;;
  *) die "repo '$REPO' is not an absolute path" ;;
esac
case "$REPO" in
  *[\&\|\<\>\"\'\\]*) die "repo '$REPO' contains a character this will not substitute" ;;
esac
/usr/bin/id "$OPERATOR" >/dev/null 2>&1 || die "no account named '$OPERATOR' on this host"

label_of() { local b; b="$(basename "$1" .plist)"; printf '%s' "$b"; }
normal() { case "$1" in online.rcsl.*) printf '%s' "$1" ;; *) printf 'online.rcsl.%s' "$1" ;; esac; }

# Which templates: the named labels, every one already installed, or (check
# mode) every template.
TEMPLATES=""
if [ -n "$LABELS" ]; then
  for l in $LABELS; do
    f="$HERE/$(normal "$l").plist"
    [ -f "$f" ] || die "no template for $l ($f)"
    TEMPLATES="$TEMPLATES $f"
  done
elif [ "$INSTALLED_ONLY" = 1 ] || [ "$MODE" = "check" ]; then
  for f in "$HERE"/online.rcsl.*.plist; do
    if [ "$MODE" = "check" ] || [ -f "$DEST/$(basename "$f")" ]; then
      TEMPLATES="$TEMPLATES $f"
    fi
  done
else
  die "name the labels to install, or pass --installed"
fi
[ -z "$RELOAD" ] || [ "$MODE" = "install" ] || die "--reload installs; it cannot be combined with --check"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

render() {
  local src="$1" out="$WORK/$(basename "$1")"
  sed -e "s|@OPERATOR@|$OPERATOR|g" -e "s|@REPO@|$REPO|g" "$src" > "$out"
  if grep -n '@[A-Z_][A-Z_]*@' "$out" >&2; then
    die "$(basename "$src") still has a placeholder after rendering"
  fi
  /usr/bin/plutil -lint -s "$out" || die "$(basename "$src") does not render to a valid plist"
  printf '%s' "$out"
}

content() { /usr/bin/plutil -convert json -o - "$1" 2>/dev/null; }

if [ "$MODE" = "check" ]; then
  drift=0
  for f in $TEMPLATES; do
    name="$(basename "$f")"
    out="$(render "$f")"
    if [ ! -f "$DEST/$name" ]; then
      printf '%-48s not installed\n' "$name"
    elif cmp -s "$out" "$DEST/$name"; then
      printf '%-48s identical\n' "$name"
    elif [ "$(content "$out")" = "$(content "$DEST/$name")" ]; then
      printf '%-48s same content, comments differ\n' "$name"
    else
      printf '%-48s CONTENT DIFFERS\n' "$name"
      drift=1
    fi
  done
  exit "$drift"
fi

[ "$(id -u)" = 0 ] || die "installing needs sudo; --check does not"

for f in $TEMPLATES; do
  out="$(render "$f")"
  install -o root -g wheel -m 644 "$out" "$DEST/$(basename "$f")"
  printf 'installed %s\n' "$(basename "$f")"
done

for l in $RELOAD; do
  label="$(normal "$l")"
  launchctl bootout "system/$label" 2>/dev/null || true
  i=0
  while launchctl print "system/$label" >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -le 120 ] || die "$label did not unload within 120 s; not bootstrapping"
    sleep 1
  done
  launchctl bootstrap system "$DEST/$label.plist"
  printf 'reloaded %s\n' "$label"
done
