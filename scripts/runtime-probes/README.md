# Runtime probes

Measurements of what the inference runtime actually does, the evidence the plan
in [#24](https://github.com/Research-Center-for-Smart-Learning-RCSL/RCSL-AI-Nexus/issues/24)
rests on. Each probe sends real requests and some load or unload models, so
each refuses to run without `--i-own-the-window`. Run them on the runtime's own
host, in a window you own, and restore residency in production order (largest
model first) if a probe does not do it for you.

Run from `backend/` so the probes can import the application:

```bash
cd backend
PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/<probe>.py --i-own-the-window ...
```

| Probe | Question | Disrupts |
|---|---|---|
| `record_prompt_counts.py` | What does the runtime count for the agreement corpus? Verifies the served manifest first | nothing beyond the requests |
| `boundary.py` | Up to what size is a prompt kept whole; what happens past it, and when output overflows | reloads the model at the test context; `--restore-ctx` puts it back |
| `residency.py` | What does loading a large model at each context do to the models beside it | evicts and reloads siblings; restores production order |
| `prefix_cache.py` | Do repeats, appends and interleaved conversations keep their prefix | occupies the model |
| `disconnect.py` | Does the runtime keep working after the client leaves; does it act on a truncated body | with `--allow-unload`, the model is unavailable for up to ~2 min |
| `reset_evidence.py` | What changes across a runtime restart (PID, start time) | waits for **you** to restart the runtime |

Every result line carries a fingerprint: runtime version, model digests, what
was resident, and the serving process's PID and start time. Results from a
different runtime, version or node are not interchangeable; the plan requires
these to be re-run per node and runtime (#24 final spec §6, §12).

What was measured on 2026-10-07/08, and on what, is in the issue comments and
`docs/progress/2026-10-08.md`.
