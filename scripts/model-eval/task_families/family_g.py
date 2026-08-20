from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# G - multi-hop arithmetic with a unit change
# --------------------------------------------------------------------------

task(
    id="capacity_chain",
    group="G",
    kind="exact",
    prompt=(
        "A cluster has 8 nodes. Each node has 64 GiB of unified memory.\n\n"
        "1. On every node, 12 GiB is reserved for the operating system and containers and is "
        "never available to the model runtime.\n"
        "2. Of the memory that remains across the whole cluster, 75% may be allocated to model "
        "weights; the rest is reserved for KV cache.\n"
        "3. Of that weights allocation, 20% is held back as headroom and is not usable.\n"
        "4. Model checkpoint files are measured in GB, where 1 GB is exactly 1,000,000,000 bytes, "
        "while the memory figures above are in GiB, where 1 GiB is exactly 1,073,741,824 bytes.\n"
        "5. The runtime's own working set takes a further 5 GB on every node, and comes out of "
        "what is left after step 3.\n"
        "6. Each checkpoint file is 4.7 GB.\n\n"
        "How many whole checkpoints fit into what remains across the cluster?\n\n"
        "Answer with a single integer." + EXACT_SUFFIX
    ),
    expected="48",
    reference="FINAL: 48",
    wrong="FINAL: 57",
)

task(
    id="retention_window",
    group="G",
    kind="exact",
    prompt=(
        "A record was created at 2026-01-31 22:40 local time in a region whose offset is "
        "UTC+08:00, and that offset does not change during the period in question.\n\n"
        "Apply these rules in order:\n\n"
        "1. The record is retained until the same clock time on the **last day of the following "
        "calendar month**, in the record's own local timezone.\n"
        "2. Express that instant in UTC.\n"
        "3. A policy ceiling applies: no record may be retained more than 30 days from its "
        "creation. If the instant from step 2 is later than the ceiling, the ceiling governs "
        "instead.\n\n"
        "Give the instant at which the record must be deleted, in UTC, in the exact format "
        "`YYYY-MM-DDTHH:MMZ`." + EXACT_SUFFIX
    ),
    expected="2026-02-28T14:40Z",
    reference="FINAL: 2026-02-28T14:40Z",
    wrong="FINAL: 2026-02-28T22:40Z",
)
