"""Stable registry for the model-evaluation task families."""

import json

from task_families.anchors import TASKS as ANCHORS_TASKS
from task_families.family_a import TASKS as FAMILY_A_TASKS
from task_families.family_b import TASKS as FAMILY_B_TASKS
from task_families.family_c import TASKS as FAMILY_C_TASKS
from task_families.family_d import TASKS as FAMILY_D_TASKS
from task_families.family_e import TASKS as FAMILY_E_TASKS
from task_families.family_f import TASKS as FAMILY_F_TASKS
from task_families.family_g import TASKS as FAMILY_G_TASKS
from task_families.family_h import TASKS as FAMILY_H_TASKS
from task_families.hard_chain import TASKS as HARD_CHAIN_TASKS
from task_families.hard_derive import TASKS as HARD_DERIVE_TASKS
from task_families.hard_refusal import TASKS as HARD_REFUSAL_TASKS
from task_families.hard_spec import TASKS as HARD_SPEC_TASKS
from task_families.hard_tutor import TASKS as HARD_TUTOR_TASKS
from task_families.hard_vm import TASKS as HARD_VM_TASKS
from task_registry import CODE_SUFFIX, EXACT_SUFFIX

TASKS: list[dict] = [
    *FAMILY_A_TASKS,
    *FAMILY_B_TASKS,
    *FAMILY_C_TASKS,
    *FAMILY_D_TASKS,
    *FAMILY_E_TASKS,
    *FAMILY_F_TASKS,
    *FAMILY_G_TASKS,
    *FAMILY_H_TASKS,
    *HARD_VM_TASKS,
    *HARD_SPEC_TASKS,
    *HARD_DERIVE_TASKS,
    *HARD_REFUSAL_TASKS,
    *HARD_CHAIN_TASKS,
    *HARD_TUTOR_TASKS,
    *ANCHORS_TASKS,
]
BY_ID = {task["id"]: task for task in TASKS}

__all__ = ["BY_ID", "CODE_SUFFIX", "EXACT_SUFFIX", "TASKS"]

def check_count(task: dict) -> int:
    if task["kind"] == "code":
        return len(task.get("checks", []))
    if task["kind"] == "dialogue":
        return sum(len(turn.get("checks", [])) for turn in task["turns"])
    return 1


def as_text(task: dict) -> str:
    """What a reader has to see to judge a score.

    An exact or code task is its prompt. A dialogue task has no single prompt --
    it is a system prompt plus a script the student follows -- and rendering
    only the system half would show the rules while hiding every attempt to
    break them, which is the half the score is actually about.
    """
    if task["kind"] != "dialogue":
        return task["prompt"]
    parts = ["[system prompt]", task["system"], ""]
    for i, turn in enumerate(task["turns"]):
        parts += [f"[student, turn {i}]", turn["student"], ""]
    return "\n".join(parts)


def definitions() -> list[dict]:
    return [
        {
            "task": t["id"],
            "group": t["group"],
            "kind": t["kind"],
            "prompt": as_text(t),
            "checks": check_count(t),
        }
        for t in TASKS
    ]


if __name__ == "__main__":
    import sys

    # `--json` feeds the evaluation importer, which stores a run's task text
    # beside its scores. It is emitted from here rather than read from the
    # repository by the backend because the admin image does not carry
    # `scripts/`, and because the text belongs to the run: `vm_trace`'s prompt
    # changed between `hard-pilot` and `hard-full` on 2026-09-03, so a screen
    # that paired an old run with today's file would be showing a question that
    # run never asked.
    if "--json" in sys.argv:
        print(json.dumps(definitions(), indent=2))
        raise SystemExit(0)
    for task in TASKS:
        print(f"{task['group']:6s} {task['id']:22s} {task['kind']:8s} "
              f"{check_count(task):3d} checks")
    print(f"\n{len(TASKS)} tasks")
