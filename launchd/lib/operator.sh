# Who this checkout belongs to, and where that account's Colima socket is.
#
# Sourced after REPO is set from the script's own location. Derived rather than
# written into each script, because the repository is public and the account
# is the operator's own login.
#
# **The account is the checkout's owner, not whoever runs the script.** Most
# jobs run as the operator, but `stop-stack-once.sh` and the Ollama adoption
# script run under sudo and `delay-tailscaled-once.sh` as root, and all of them
# need the operator's Colima. `$HOME` is not used: launchd and `sudo -u` without
# `-H` hand a job someone else's (the 2026-09-09 `sudo -u` finding), and a
# DOCKER_HOST under the wrong home reaches no daemon. The directory service
# answers by account name whatever the environment.
#
# Refuses rather than guesses: a job that cannot name its docker socket would
# otherwise report every container as down.

OPERATOR="$(/usr/bin/stat -f %Su "$REPO" 2>/dev/null)"
OPERATOR_HOME="$(/usr/bin/dscl . -read "/Users/${OPERATOR:-?}" NFSHomeDirectory 2>/dev/null \
  | /usr/bin/awk '/^NFSHomeDirectory:/ {print $2}')"
if [ -z "$OPERATOR" ] || [ "$OPERATOR" = "root" ] || [ -z "$OPERATOR_HOME" ]; then
  printf '%s FATAL: cannot resolve the operator of %s (owner=%s home=%s)\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$REPO" "${OPERATOR:-}" "${OPERATOR_HOME:-}" >&2
  exit 1
fi
export DOCKER_HOST="unix://$OPERATOR_HOME/.colima/default/docker.sock"
