import sys

from agent_loop.config import MODEL, THINK
from agent_loop.reporting import TOTALS
from agent_loop.rungs_basic import rung1, rung2, rung3, rung4, rung5, rung6, rung7, rung8
from agent_loop.rungs_repository import rung9, rung10

RUNGS = {
    1: rung1,
    2: rung2,
    3: rung3,
    4: rung4,
    5: rung5,
    6: rung6,
    7: rung7,
    8: rung8,
    9: rung9,
    10: rung10,
}


def run(which: int) -> None:
    for field in TOTALS:
        TOTALS[field] = type(TOTALS[field])()
    print(f"--- rung {which}   model={MODEL}  think={THINK} ---")
    RUNGS[which]()
    print(
        f"  TOTAL {TOTALS['turns']} turns  {TOTALS['seconds']:.1f}s  "
        f"prompt={TOTALS['prompt']}  completion={TOTALS['completion']}"
    )


def main(argv: list[str], help_text: str | None = None) -> None:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        sys.exit(help_text or "usage: measure-agent-loop.py {1..10|all}")
    if argv[1] == "all":
        for which in sorted(RUNGS):
            run(which)
            print()
        return
    try:
        which = int(argv[1])
    except ValueError:
        sys.exit(f"not a rung: {argv[1]!r}. Give 1..{max(RUNGS)} or 'all'.")
    if which not in RUNGS:
        sys.exit(f"no rung {which}. Give 1..{max(RUNGS)} or 'all'.")
    run(which)
