#!/bin/bash
# End-to-end evaluation run. Resumes where it left off: run.py skips completed
# samples, and each phase gate file records whether a phase finished. Kill it
# at any point and re-run — the only cost is re-validating and re-printing
# the analysis (both are fast).
#
# The restore trap fires on any exit, including SIGTERM and SIGKILL of the
# wrapper. The trap spawns restore in a new session so a process-group kill
# does not take it down with the wrapper — the same fix run.py 2026-09-04
# applied to its own trap after losing the deployment to exactly that.

set -euo pipefail
cd "$(dirname "$0")"

GATE_DIR=".phase-gates"
mkdir -p "$GATE_DIR"

gate() { touch "$GATE_DIR/$1"; }
gated() { [ -f "$GATE_DIR/$1" ]; }

restore_deployment() {
    echo ""
    echo "=== restoring deployment ==="
    python3 -c "
import os, subprocess, sys
os.setsid()
subprocess.run([sys.executable, 'run.py', 'restore'])
" &
    RESTORE_PID=$!
    wait "$RESTORE_PID" 2>/dev/null || true
}
trap restore_deployment EXIT

echo "=== validate ==="
python3 validate.py
echo ""

if ! gated "hard-pilot-3"; then
    echo "=== hard-pilot-3 (calibration) ==="
    python3 run.py hard-pilot-3
    gate "hard-pilot-3"
fi
echo "--- hard-pilot-3 analysis ---"
python3 analyse.py hard-pilot-3
echo ""

if ! gated "hard-full-3"; then
    echo "=== hard-full-3 (main measurement) ==="
    python3 run.py hard-full-3
    gate "hard-full-3"
fi
echo "--- hard-full-3 analysis ---"
python3 analyse.py hard-full-3
echo ""

if ! gated "tutor-pilot"; then
    echo "=== tutor-pilot (education calibration) ==="
    python3 run.py tutor-pilot
    gate "tutor-pilot"
fi
echo "--- tutor-pilot analysis ---"
python3 analyse.py tutor-pilot
echo ""

if ! gated "tutor-full"; then
    echo "=== tutor-full (education agent) ==="
    python3 run.py tutor-full
    gate "tutor-full"
fi
echo "--- tutor-full analysis ---"
python3 analyse.py tutor-full
echo ""

echo "=== JSON export ==="
python3 analyse.py hard-full-3 --json > hard-full-3.json
python3 analyse.py tutor-full --json > tutor-full.json
echo "written to hard-full-3.json and tutor-full.json"

echo ""
echo "=== all phases complete ==="
