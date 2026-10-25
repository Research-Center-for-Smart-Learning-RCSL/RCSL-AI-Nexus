# Reuse the established Tier 1 mail path; Prometheus owns the pending timers.
# Collapse instance labels to stable alert names so a process restart does not
# create notification churn. A query failure is itself a Tier 1 failure.
#
# **A planned maintenance hold is not an outage (#61).** An entry releases every
# runtime on purpose, so "no capability is available" and "the resident set does
# not match what operators asked for" are the hold working, not failing. While
# the platform's public status says it is closed, those alerts are reported as
# expected in the digest instead of mailing FAILING every five minutes. Every
# other alert still fails: an unresolved operation, a stale observer or a
# reconciler that gave up is wrong during a hold too. An unreadable status counts
# as open, so a broken admin never hides an outage.
EXPECTED_DURING_MAINTENANCE="NexusCapabilityUnavailable NexusModelResidencyMismatch NexusSilentInferenceOutage"

MAINTENANCE_CLOSED=0
MAINTENANCE_STATUS="$(curl -s -m 5 http://127.0.0.1:8001/admin/maintenance/status 2>/dev/null)"
if [ "$(printf '%s' "$MAINTENANCE_STATUS" | /usr/bin/python3 -c '
import json, sys
try:
    print(1 if json.load(sys.stdin).get("closed") is True else 0)
except Exception:
    print(0)
' 2>/dev/null)" = "1" ]; then
  MAINTENANCE_CLOSED=1
  note "platform closed for planned maintenance; runtime availability alerts are expected"
fi

if [ "$PROM_OK" -eq 1 ]; then
  AVAILABILITY_ALERTS="$(prom_get pairs 'count by (alertname) (ALERTS{alertstate="firing",alertname=~"NexusCapabilityUnavailable|NexusNodeOperationUnresolved|NexusSilentInferenceOutage|NexusAvailabilityObserverStale|NexusModelResidencyMismatch|NexusResidencyReconcilerGaveUp"})' alertname)"
  if [ $? -ne 0 ]; then
    fail "availability-query" "Could not read inference availability alerts from Prometheus."
  elif [ -n "$AVAILABILITY_ALERTS" ]; then
    while read -r alert count; do
      [ -n "$alert" ] || continue
      if [ "$MAINTENANCE_CLOSED" -eq 1 ] && case " $EXPECTED_DURING_MAINTENANCE " in *" $alert "*) true ;; *) false ;; esac; then
        note "$alert is firing for $count series, expected while closed for maintenance"
        continue
      fi
      fail "availability-$alert" "$alert is firing for $count series; inspect Prometheus and GET /admin/capabilities/availability."
    done <<EOF
$AVAILABILITY_ALERTS
EOF
  else
    note "inference availability: no firing alerts"
  fi
fi
