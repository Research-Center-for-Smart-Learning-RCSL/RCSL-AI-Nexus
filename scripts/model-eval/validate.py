"""Section 4.1: validate the scorer in both directions, before any model runs.

Every task's reference answer must score 1.0 and its deliberately wrong answer
must score below 1.0. A scorer that accepts a wrong answer is worse than no
measurement, so this exits non-zero and the run does not proceed.
"""

import sys
import time

from harness import score
from tasks import TASKS


def main() -> int:
    bad = 0
    print(f"{'task':24s} {'ref':>6s} {'wrong':>6s}  verdict")
    print("-" * 62)
    for t in TASKS:
        t0 = time.time()
        ref, ref_detail = score(t, t["reference"])
        wrong, wrong_detail = score(t, t["wrong"])
        ok_ref = ref == 1.0
        ok_wrong = wrong < 1.0
        verdict = "ok" if (ok_ref and ok_wrong) else "FAIL"
        if verdict == "FAIL":
            bad += 1
        print(f"{t['id']:24s} {ref:6.2f} {wrong:6.2f}  {verdict}  ({time.time()-t0:.1f}s)")
        if not ok_ref:
            for name, passed, msg in ref_detail:
                if not passed:
                    print(f"    reference failed {name!r}: {msg}")
        if not ok_wrong:
            print("    the wrong answer scored full marks - the scorer is blind here")
            for name, passed, _ in wrong_detail:
                print(f"    {'pass' if passed else 'FAIL'} {name}")
    print("-" * 62)
    print(f"{len(TASKS) - bad}/{len(TASKS)} tasks have a scorer that works in both directions")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
