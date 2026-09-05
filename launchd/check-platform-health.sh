#!/bin/bash
# Watch the platform, mail when something breaks, and mail a summary once a day.
#
# Why this exists. On 2026-07-26 the first reboot left nine containers running,
# the gateway reporting `healthy`, and four of six published ports unbound. The
# platform was unreachable from the tailnet and nothing anywhere said so: SSH
# worked, `tailscale serve` worked, `docker compose ps` looked perfect. It was
# found because a person sat and read four logs. `reconcile-port-bindings.sh`
# now repairs that at boot, but a repair that fails, or a daemon that never runs,
# would land in exactly the same silence. This closes that: the state is checked
# on an interval and a change is mailed out.
#
# What it can and cannot see. It runs on the machine it watches, so it reports
# "up but not serving" — the observed failure — and cannot report "the machine is
# off". The daily digest below is what covers that: if the mail stops arriving,
# something is wrong even though no alert was sent. Silence is only evidence when
# something is expected to break it. That remains the weakest joint here, because
# it needs a person to notice an absence; an external dead man's switch is the
# real fix and is deliberately not built yet.
#
# **Two tiers, and the split is the design.** Tier 1 is "broken now": it goes into
# the signature, and any change to that signature mails immediately. Tier 2 is
# "will break, or is degrading": expiries, staleness, growth. Tier 2 never enters
# the signature and never sends its own mail — it is reported once a day in the
# digest. The reason is that a fourteen-day expiry warning in the signature keeps
# the subject line reading FAILING for fourteen days, and a subject that means
# nothing is worse than no subject at all. Anything with lead time waits for the
# digest; anything without it wakes somebody.
#
# Every check is written so it can produce more than one answer. The service
# check compares against an expected list rather than enumerating what happens to
# be running, because a container that is simply gone would otherwise not appear
# in the enumeration and the sweep would report success. That is the same error
# the reconciler's third precondition exists for, and the same one that made
# `tailscale status --json` answer "no SSH host keys" to a question it did not
# have a field for. That failure repeated itself while this file was being
# extended: `Self` carries no `KeyExpiry` field at all when key expiry is
# disabled, so a check reading it would have been a permanent silent pass. See
# check 13 for the three answers it gives instead.
#
# Written for the bash 3.2 that macOS ships: no mapfile, no associative arrays.
# `/usr/bin/python3` is used for JSON and dates only, stdlib-only and never a
# virtualenv, for the reason online.rcsl.host-metrics.plist gives: a launchd job
# that depends on a project venv breaks the first time the project is rebuilt.

set -uo pipefail

REPO="/Users/rcslmac1/dev/RCSL-AI-Nexus"
export DOCKER_HOST="unix:///Users/rcslmac1/.colima/default/docker.sock"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Where the alerts go. Not a secret; kept here so it is reviewable in git rather
# than sitting in an untracked file nobody reads. Space-separated: each address
# gets its own envelope recipient, and the To: header is built from the same list
# below so what the mail says and what the envelope does cannot drift apart.
ALERT_TO="leolove3very@gmail.com shaniawang06@gmail.com"

# The sending account and its app password. Two files, following the one-file-per
# -credential convention in secrets/README.md. Gmail requires the envelope sender
# to be the account that authenticates, so both come from the same pair.
ACCOUNT_FILE="$REPO/secrets/alert_smtp_account"
PASSWORD_FILE="$REPO/secrets/alert_smtp_password"
SMTP_URL="smtps://smtp.gmail.com:465"

# The state file is also the liveness record: its mtime is the last run. The log
# carries only events, so an empty log means "nothing happened", and "did this
# ever run" is answered here instead. A log that is quiet for both reasons would
# be the ambiguity this whole script exists to remove.
#
# Three lines, and every path that writes it writes all three:
#   1  the tier-1 signature
#   2  the date of the last digest, YYYY-MM-DD
#   3  restart counts at the last run, "service:count service:count"
#
# Line 2 held a Unix timestamp before 2026-08-04, when the digest was a rolling
# 24-hour heartbeat. A leftover timestamp does not parse as a date and is read as
# "no digest yet", which sends one at the next run — that is the intended
# upgrade path and it doubles as proof the new mail reaches both recipients.
STATE_FILE="/opt/homebrew/var/nexus-health.state"

HEALTH_LOG="/opt/homebrew/var/log/nexus-health.log"
RECONCILE_LOG="/opt/homebrew/var/log/nexus-reconcile.log"

# `NEXUS_HEALTH_DRY_RUN=1 bash check-platform-health.sh` runs every check and
# prints the mail it would have sent instead of sending it, and writes no state.
# Both halves matter: a dry run that wrote state would consume the digest date
# and the real run would then skip the day it was meant to verify. This exists
# because the alternative way to test a mailer is to mail somebody.
DRY_RUN="${NEXUS_HEALTH_DRY_RUN:-0}"

# The digest goes out at 08:00 local time, not 24 hours after the last one. The
# rolling version drifted — any mail reset its clock — so its arrival time
# wandered through the day and "today's mail has not come yet" was never a
# statement anyone could make. A fixed hour makes an absence legible, which is
# the only thing that makes a digest worth sending at all. The machine is on
# Asia/Taipei, so this is 08:00 UTC+8.
DIGEST_HOUR=8

# Long-lived services, which is every compose service except `migrate`. `migrate`
# is a one-shot job and is correctly `Exited (0)` after a boot; treating it as
# expected-running would alert on every reboot forever.
#
# Derived from the compose file at run time, with this list as the fallback for
# when that derivation fails. It was a hand-maintained literal until 2026-08-04
# and `parser` and `qdrant` were missing from it, so either could have stopped
# without the sweep noticing — the list is compared against, and a service absent
# from it is a service nothing asks about. That is the enumeration error the
# header argues against, in the list the argument is about. Deriving it means
# adding a service to docker-compose.yml is enough; nobody has to remember.
EXPECTED_SERVICES="postgres redis prometheus grafana gateway admin-public admin-tailnet frontend-public frontend-tailnet parser qdrant"

# Boot grace. The reconciler owns the first minutes: it waits for the tailnet
# address, the daemon, and the container set to settle, which can legitimately
# take a couple of minutes. Alerting inside that window would mail out a failure
# that is about to be repaired, and the first thing anyone would learn is to
# ignore the alerts.
#
# 240 rather than 300, and the difference is the whole point. The plist fires
# this every 300 seconds, so a grace of 300 puts the first post-boot run exactly
# on the boundary: whether it evaluates or is skipped comes down to how many
# seconds launchd took to load the job. Either answer is defensible; a coin flip
# between them is not, because it decides whether the first real check of a boot
# happens at five minutes or at ten. 240 is below the interval by a clear margin,
# so the boot-time run (RunAtLoad) is suppressed and every scheduled run after it
# evaluates.
#
# This value had never once been read. `sysctl -n kern.boottime` prints
# `{ sec = 1785068938, usec = 428375 } ...` and the expression that parsed it was
# `s/.*sec = \([0-9]*\).*/\1/`, whose leading `.*` is greedy and therefore matched
# through to `usec`. BOOT_SEC was the microseconds field, uptime came out as the
# whole Unix epoch, and the comparison below could only ever say "not in grace" —
# the same defect this repository keeps finding, in the check whose entire job was
# to have two answers. It also put a nine-digit `uptime` line in every alert mail
# sent before 2026-07-26 20:45. The anchor is what fixes it: the field wanted is
# the one at the start of the line.
BOOT_GRACE=240

# --- thresholds -------------------------------------------------------------
#
# Tier 1 numbers are where the platform is already failing or is hours away from
# it. Tier 2 numbers are where somebody should put it on a list. Two disk
# numbers rather than one for exactly that reason: 85% is a chore, 95% is an
# outage, because Postgres goes read-only when the volume fills.

GEOIP_MAX_AGE_DAYS=10        # refreshed weekly, so 10 days is two missed runs
DISK_WARN_PCT=85
DISK_FAIL_PCT=95
MEM_AVAIL_WARN_GB=4
SWAP_WARN_GB=8
DOCKER_RECLAIM_WARN_GB=30
KEY_EXPIRY_WARN_DAYS=30
# Mirrors DEFAULT_RETENTION_DAYS in backend/app/domain/entities/retention.py.
# Duplicated because this runs outside the application, and named here so the
# duplication is visible rather than buried in a SQL literal. An absent policy
# row *means* this number — `ManageRetention._days_for` returns it — so reading
# "no row" as "nothing is being deleted" is wrong in both directions: it invents
# a problem that does not exist and it skips the check for the one that does.
DEFAULT_RETENTION_DAYS=360
TS_KEY_WARN_DAYS=21
HTTP_5XX_RATIO=0.05
HTTP_5XX_MIN_SAMPLE=20       # below this a single error is 100% and means nothing

# Ordered stages; each is sourced so exit codes and shared state remain unchanged.
. "$REPO/launchd/lib/health/common.sh"
. "$REPO/launchd/lib/health/state.sh"
. "$REPO/launchd/lib/health/service_checks.sh"
. "$REPO/launchd/lib/health/probes.sh"
. "$REPO/launchd/lib/health/metrics.sh"
. "$REPO/launchd/lib/health/backup_check.sh"
. "$REPO/launchd/lib/health/transitions.sh"
. "$REPO/launchd/lib/health/mail.sh"
