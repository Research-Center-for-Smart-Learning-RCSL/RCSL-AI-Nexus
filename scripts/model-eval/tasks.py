"""Stable registry for the model-evaluation task families."""

from task_families.anchors import TASKS as ANCHORS_TASKS
from task_families.family_a import TASKS as FAMILY_A_TASKS
from task_families.family_b import TASKS as FAMILY_B_TASKS
from task_families.family_c import TASKS as FAMILY_C_TASKS
from task_families.family_d import TASKS as FAMILY_D_TASKS
from task_families.family_e import TASKS as FAMILY_E_TASKS
from task_families.family_f import TASKS as FAMILY_F_TASKS
from task_families.family_g import TASKS as FAMILY_G_TASKS
from task_families.family_h import TASKS as FAMILY_H_TASKS
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
    *ANCHORS_TASKS,
]
BY_ID = {task["id"]: task for task in TASKS}

__all__ = ["BY_ID", "CODE_SUFFIX", "EXACT_SUFFIX", "TASKS"]

if __name__ == "__main__":
    for task in TASKS:
        checks = len(task.get("checks", [])) if task["kind"] == "code" else 1
        print(f"{task['group']:6s} {task['id']:22s} {task['kind']:6s} {checks:2d} checks")
    print(f"\n{len(TASKS)} tasks")
