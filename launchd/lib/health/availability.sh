# Reuse the established Tier 1 mail path; Prometheus owns the pending timers.
# Collapse instance labels to stable alert names so a process restart does not
# create notification churn. A query failure is itself a Tier 1 failure.
if [ "$PROM_OK" -eq 1 ]; then
  AVAILABILITY_ALERTS="$(prom_get pairs 'count by (alertname) (ALERTS{alertstate="firing",alertname=~"NexusCapabilityUnavailable|NexusNodeOperationUnresolved|NexusSilentInferenceOutage|NexusAvailabilityObserverStale|NexusModelResidencyMismatch|NexusResidencyReconcilerGaveUp"})' alertname)"
  if [ $? -ne 0 ]; then
    fail "availability-query" "Could not read inference availability alerts from Prometheus."
  elif [ -n "$AVAILABILITY_ALERTS" ]; then
    while read -r alert count; do
      [ -n "$alert" ] || continue
      fail "availability-$alert" "$alert is firing for $count series; inspect Prometheus and GET /admin/capabilities/availability."
    done <<EOF
$AVAILABILITY_ALERTS
EOF
  else
    note "inference availability: no firing alerts"
  fi
fi
