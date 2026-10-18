"""Stage the mailer's Tier 1 input without invoking any mail command."""

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="host health job runs on Unix")
STAGE = Path(__file__).resolve().parents[3] / "launchd/lib/health/availability.sh"


@pytest.mark.parametrize(
    ("answer", "status", "expected"),
    [
        ("NexusCapabilityUnavailable 1", 0, "availability-NexusCapabilityUnavailable"),
        ("NexusNodeOperationUnresolved 2", 0, "availability-NexusNodeOperationUnresolved"),
        ("NexusSilentInferenceOutage 1", 0, "availability-NexusSilentInferenceOutage"),
        ("NexusAvailabilityObserverStale 1", 0, "availability-NexusAvailabilityObserverStale"),
        ("NexusModelResidencyMismatch 1", 0, "availability-NexusModelResidencyMismatch"),
        ("NexusResidencyReconcilerGaveUp 1", 0, "availability-NexusResidencyReconcilerGaveUp"),
        ("", 1, "availability-query"),
        ("", 0, "no firing alerts"),
    ],
)
def test_firing_recovery_and_query_failure(answer, status, expected):
    script = """
set -u
PROM_OK=1
prom_get() { printf '%s' "$TEST_ANSWER"; return "$TEST_STATUS"; }
fail() { printf 'FAIL %s\n' "$1"; }
note() { printf 'NOTE %s\n' "$1"; }
. "$1"
"""
    result = subprocess.run(  # noqa: S603 - fixed local shell and reviewed stage
        ["/bin/bash", "-c", script, "health-test", str(STAGE)],
        env={**os.environ, "TEST_ANSWER": answer, "TEST_STATUS": str(status)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout


def test_every_availability_rule_is_delivered():
    # The stage above stubs Prometheus, so it cannot notice an alert that the
    # query's name filter leaves out. A rule nobody mails is a silent rule.
    rules = STAGE.parents[3] / "prometheus/availability.rules.yml"
    names = re.findall(r"^\s*- alert: (\w+)$", rules.read_text(), re.MULTILINE)
    query = re.search(r'alertname=~"([^"]+)"', STAGE.read_text())
    assert names
    assert query is not None
    assert set(query.group(1).split("|")) == set(names)
