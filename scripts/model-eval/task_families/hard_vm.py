from task_registry import CODE_SUFFIX, EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# J - an invented ISA, so nothing can be recalled and everything must be read
# --------------------------------------------------------------------------

# The spec is written once and shared by both tasks so that the two of them are
# measuring the same rules: a model that misreads ROT should lose points on the
# trace and on the implementation, and the pair of scores then says whether the
# failure was in reading the spec or in executing it by hand.
ISA = """The Kestrel-2 machine has four registers r0, r1, r2 and r3, each holding an \
unsigned 64-bit integer, a program counter, and a single comparison flag. All arithmetic \
is modulo 2**64. At the start of execution every register is 0, the flag is 0 and the \
program counter is 0.

A program is a list of instructions. An instruction is a tuple whose first element is the \
opcode, a string. Operands are written as follows:

- a register operand is one of the strings "r0", "r1", "r2", "r3";
- an immediate operand is a string "#N", where N is a decimal integer with 0 <= N < 2**64;
- a jump operand is a Python int, which may be negative.

The nine opcodes are:

- ("SET", dst, src) - dst is a register operand and src is a register or immediate operand; \
stores the value of src in dst.
- ("ADD", dst, src) - adds the value of src to dst.
- ("SUB", dst, src) - subtracts the value of src from dst.
- ("MUL", dst, src) - multiplies dst by the value of src.
- ("CMP", a, b) - a and b are register or immediate operands; sets the flag to 1 if the \
value of a is strictly less than the value of b, and to 0 otherwise.
- ("JMP", off) - jumps.
- ("JIF", off) - jumps if the flag is 1, and otherwise does nothing.
- ("ROT",) - replaces (r0, r1, r2, r3) with (r1, r2, r3, r0).
- ("HALT",) - stops execution.

Execution rules:

- Instruction addresses are 0-based positions in the program list.
- CMP is the only opcode that writes the flag.
- The target of a JMP, and of a JIF that jumps, is the address of that jump instruction \
plus off.
- Every instruction other than a jump that is taken advances the program counter to the \
next address.
- Executing any instruction, including HALT and including a jump whose target is out of \
range, counts as one step.

Before each instruction is fetched, in this order: if the program counter is outside the \
range 0 to len(program) - 1, execution stops with reason "fell_off" and the program \
counter keeps that value; otherwise, if the number of steps already executed equals \
max_steps, execution stops with reason "step_limit" and the program counter is the \
address that was about to be fetched.

Execution also stops when a HALT is executed, with reason "halt" and the program counter \
equal to the address of that HALT; and when a JMP or a jumping JIF computes a target \
outside the range 0 to len(program) - 1, with reason "bad_jump" and the program counter \
equal to the address of that jump instruction."""

_TRACE_PROGRAM = """```
 0  ("SET", "r0", "#1")
 1  ("SET", "r1", "#0")
 2  ("SET", "r2", "#5")
 3  ("SET", "r3", "#6364136223846793005")
 4  ("CMP", "r1", "#4")
 5  ("JIF", 2)
 6  ("JMP", 10)
 7  ("MUL", "r0", "r3")
 8  ("ROT",)
 9  ("ADD", "r3", "#7")
10  ("ROT",)
11  ("ROT",)
12  ("ROT",)
13  ("ADD", "r1", "#1")
14  ("JMP", -10)
15  ("HALT",)
16  ("CMP", "r1", "#1000000")
17  ("ADD", "r2", "#100")
18  ("ROT",)
19  ("MUL", "r2", "#3")
20  ("JIF", 4)
21  ("SET", "r0", "#999")
22  ("MUL", "r0", "#2")
23  ("SUB", "r1", "#4")
24  ("ADD", "r2", "#5")
25  ("ROT",)
26  ("HALT",)
```"""

# The original vm_trace asked the model to trace 55 steps of a program using
# twenty-digit numbers under modular arithmetic: 0.00 for all four candidates
# across two phases with budgets from 6,144 to 12,288. The property being
# measured -- compounding error through a loop -- was real, but the numbers
# ensured no model could produce a correct answer.
#
# This replacement keeps the same ISA, the same loop structure, and the same
# question ("what is the final register state"), but the program uses small
# constants and runs for five iterations with no arithmetic exceeding three
# digits. A model can reason about it without writing a ten-thousand-token
# trace, and the answer line is under fifty tokens.
#
# The compounding comes from the multiplier (r2) changing each iteration: r0 is
# multiplied by 5, then 4, then 3, then 2, then 1, while r1 accumulates r0 at
# each step. The result is r0 = 5! = 120 and r1 = 5 + 20 + 60 + 120 + 120 =
# 325. The CMP boundary at r2 < 1 is the designed near-miss: a model that reads
# it as r2 <= 1 exits one iteration early, giving r1 = 205.
_COMPACT_PROGRAM = """```
 0  ("SET", "r0", "#1")
 1  ("SET", "r1", "#0")
 2  ("SET", "r2", "#5")
 3  ("MUL", "r0", "r2")
 4  ("ADD", "r1", "r0")
 5  ("SUB", "r2", "#1")
 6  ("CMP", "r2", "#1")
 7  ("JIF", 2)
 8  ("JMP", -5)
 9  ("HALT",)
```"""

task(
    id="vm_accumulate",
    group="J",
    kind="exact",
    prompt=(
        ISA + "\n\nExecute the following program with max_steps = 10000.\n\n"
        + _COMPACT_PROGRAM
        + "\n\nThe left-hand column is the address and is not part of the instruction.\n\n"
        "Report the register file when execution stops, as four unsigned decimal integers, "
        "on a final line of exactly this form:\n"
        "FINAL: r0=<n> r1=<n> r2=<n> r3=<n>" + EXACT_SUFFIX
    ),
    expected="r0=120 r1=325 r2=0 r3=0",
    reference="FINAL: r0=120 r1=325 r2=0 r3=0",
    wrong="FINAL: r0=120 r1=205 r2=1 r3=0",
)


# Separates models that implement every clause of a spec they have just read from
# models that implement the ISA they already know: the checks that fail first are
# the flag that outlives its CMP, the direction of ROT, and relative jumps.
task(
    id="vm_implement",
    group="J",
    kind="code",
    prompt=(
        ISA + "\n\nWrite a Python function `run(program, max_steps)` that executes a "
        "Kestrel-2 program and returns a dict with exactly these keys:\n\n"
        "- `\"regs\"`: a list of the four register values, in the order r0, r1, r2, r3\n"
        "- `\"flag\"`: the flag, 0 or 1\n"
        "- `\"pc\"`: the program counter\n"
        "- `\"steps\"`: the number of steps executed\n"
        "- `\"reason\"`: one of the strings \"halt\", \"bad_jump\", \"fell_off\", \"step_limit\"\n\n"
        "`program` is a list of instruction tuples as described above and `max_steps` is a "
        "non-negative integer. The program is well formed; no validation is required."
        + CODE_SUFFIX
    ),
    setup="""
_M = 1 << 64

def _regs(program, max_steps):
    return run(program, max_steps)["regs"]

# The trace program from the companion task, kept here so the end-to-end checks
# exercise the same interactions the hand-trace does.
_LOOP = [
    ("SET", "r0", "#1"), ("SET", "r1", "#0"), ("SET", "r2", "#5"),
    ("SET", "r3", "#6364136223846793005"), ("CMP", "r1", "#10"), ("JIF", 2),
    ("JMP", 10), ("MUL", "r0", "r3"), ("ROT",), ("ADD", "r3", "#7"), ("ROT",),
    ("ROT",), ("ROT",), ("ADD", "r1", "#1"), ("JMP", -10), ("HALT",),
    ("CMP", "r1", "#1000000"), ("ADD", "r2", "#100"), ("ROT",), ("MUL", "r2", "#3"),
    ("JIF", 4), ("SET", "r0", "#999"), ("MUL", "r0", "#2"), ("SUB", "r1", "#4"),
    ("ADD", "r2", "#5"), ("ROT",), ("HALT",),
]
_LOOP_REGS = [105, 645664597830827404, 8159125163526397555, 10]
""",
    checks=[
        ("empty program", """
_r = run([], 100)
assert _r["reason"] == "fell_off", _r
assert _r["regs"] == [0, 0, 0, 0], _r
assert _r["pc"] == 0 and _r["steps"] == 0, _r
assert _r["flag"] == 0, _r
""", 15),
        ("SET from immediate and from register", """
_r = run([("SET", "r0", "#42"), ("SET", "r2", "r0"), ("HALT",)], 100)
assert _r["regs"] == [42, 0, 42, 0], _r
""", 15),
        ("ADD and SUB, immediate and register", """
_r = run([("SET", "r0", "#10"), ("ADD", "r0", "#5"), ("SET", "r1", "r0"),
          ("SUB", "r1", "#6"), ("ADD", "r1", "r0"), ("HALT",)], 100)
assert _r["regs"] == [15, 24, 0, 0], _r
""", 15),
        ("MUL and arithmetic wrap at 2**64", """
_r = run([("SET", "r0", "#18446744073709551615"), ("ADD", "r0", "#3"),
          ("SET", "r1", "#4294967296"), ("MUL", "r1", "r1"),
          ("SET", "r2", "#0"), ("SUB", "r2", "#1"), ("HALT",)], 100)
assert _r["regs"] == [2, 0, _M - 1, 0], _r
""", 15),
        ("CMP is strictly less than", """
assert _regs([("CMP", "#3", "#4"), ("SET", "r0", "#1"), ("HALT",)], 100) == [1, 0, 0, 0]
_r = run([("CMP", "#3", "#4"), ("HALT",)], 100)
assert _r["flag"] == 1, _r
_r = run([("CMP", "#4", "#4"), ("HALT",)], 100)
assert _r["flag"] == 0, _r
_r = run([("SET", "r0", "#9"), ("CMP", "r0", "#4"), ("HALT",)], 100)
assert _r["flag"] == 0, _r
""", 15),
        ("the flag outlives the instructions between CMP and JIF", """
_r = run([("CMP", "#1", "#2"), ("SET", "r0", "#7"), ("MUL", "r0", "#2"),
          ("ADD", "r0", "#1"), ("JIF", 3), ("SET", "r1", "#100"), ("HALT",),
          ("SET", "r2", "#5"), ("HALT",)], 100)
assert _r["regs"] == [15, 0, 5, 0], _r
""", 15),
        ("JIF with the flag clear falls through", """
_r = run([("CMP", "#4", "#4"), ("JIF", 3), ("SET", "r0", "#1"), ("HALT",),
          ("SET", "r0", "#2"), ("HALT",)], 100)
assert _r["regs"] == [1, 0, 0, 0], _r
""", 15),
        ("a JIF that jumps leaves the flag set for the next JIF", """
_r = run([("CMP", "#1", "#2"), ("JIF", 2), ("HALT",), ("JIF", 2), ("HALT",),
          ("SET", "r0", "#3"), ("HALT",)], 100)
assert _r["regs"] == [3, 0, 0, 0], _r
assert _r["flag"] == 1, _r
""", 15),
        ("ROT moves each register down one place", """
_r = run([("SET", "r0", "#1"), ("SET", "r1", "#2"), ("SET", "r2", "#3"),
          ("SET", "r3", "#4"), ("ROT",), ("HALT",)], 100)
assert _r["regs"] == [2, 3, 4, 1], _r
_r = run([("SET", "r0", "#1"), ("SET", "r1", "#2"), ("SET", "r2", "#3"),
          ("SET", "r3", "#4"), ("ROT",), ("ROT",), ("ROT",), ("HALT",)], 100)
assert _r["regs"] == [4, 1, 2, 3], _r
""", 15),
        ("ROT does not disturb the flag", """
_r = run([("CMP", "#1", "#2"), ("ROT",), ("ROT",), ("HALT",)], 100)
assert _r["flag"] == 1, _r
""", 15),
        ("jump offsets are measured from the jump itself", """
_r = run([("SET", "r0", "#1"), ("JMP", 2), ("SET", "r1", "#1"), ("SET", "r2", "#1"),
          ("HALT",)], 100)
assert _r["regs"] == [1, 0, 1, 0], _r
assert _r["pc"] == 4, _r
""", 15),
        ("a negative offset repeats a block", """
_r = run([("SET", "r0", "#0"), ("ADD", "r0", "#1"), ("CMP", "r0", "#4"),
          ("JIF", -2), ("HALT",)], 100)
assert _r["regs"] == [4, 0, 0, 0], _r
assert _r["steps"] == 14, _r
""", 15),
        ("a target outside the program is a bad jump", """
_r = run([("SET", "r0", "#1"), ("JMP", 9), ("HALT",)], 100)
assert _r["reason"] == "bad_jump", _r
assert _r["pc"] == 1 and _r["steps"] == 2, _r
_r = run([("SET", "r0", "#1"), ("JMP", -5), ("HALT",)], 100)
assert _r["reason"] == "bad_jump" and _r["pc"] == 1, _r
""", 15),
        ("running off the end and stopping on HALT", """
_r = run([("SET", "r0", "#1"), ("SET", "r1", "#2")], 100)
assert _r["reason"] == "fell_off", _r
assert _r["pc"] == 2 and _r["steps"] == 2, _r
_r = run([("SET", "r0", "#1"), ("HALT",), ("SET", "r0", "#9")], 100)
assert _r["reason"] == "halt", _r
assert _r["pc"] == 1 and _r["steps"] == 2, _r
""", 15),
        ("the step limit", """
_r = run([("ADD", "r0", "#1"), ("JMP", -1)], 7)
assert _r["reason"] == "step_limit", _r
assert _r["steps"] == 7 and _r["pc"] == 1, _r
assert _r["regs"] == [4, 0, 0, 0], _r
_r = run([("HALT",)], 0)
assert _r["reason"] == "step_limit", _r
assert _r["steps"] == 0 and _r["pc"] == 0, _r
""", 15),
        ("a loop, a rotation and a stale flag together", """
_r = run(_LOOP, 10000)
assert _r["regs"] == _LOOP_REGS, _r
assert _r["reason"] == "halt", _r
assert _r["pc"] == 26 and _r["steps"] == 115, _r
_r = run(_LOOP, 50)
assert _r["reason"] == "step_limit" and _r["steps"] == 50, _r
""", 20),
    ],
    reference="""
```python
_M = 1 << 64


def run(program, max_steps):
    regs = [0, 0, 0, 0]
    flag = 0
    pc = 0
    steps = 0
    n = len(program)

    def value(operand):
        if operand[0] == "r":
            return regs[int(operand[1:])]
        return int(operand[1:]) % _M

    def result(reason):
        return {"regs": regs, "flag": flag, "pc": pc, "steps": steps, "reason": reason}

    while True:
        if pc < 0 or pc >= n:
            return result("fell_off")
        if steps >= max_steps:
            return result("step_limit")
        ins = program[pc]
        op = ins[0]
        steps += 1
        if op == "HALT":
            return result("halt")
        if op in ("JMP", "JIF"):
            if op == "JIF" and flag != 1:
                pc += 1
                continue
            target = pc + ins[1]
            if target < 0 or target >= n:
                return result("bad_jump")
            pc = target
            continue
        if op == "CMP":
            flag = 1 if value(ins[1]) < value(ins[2]) else 0
        elif op == "ROT":
            regs = [regs[1], regs[2], regs[3], regs[0]]
        else:
            dst = int(ins[1][1:])
            src = value(ins[2])
            if op == "SET":
                regs[dst] = src
            elif op == "ADD":
                regs[dst] = (regs[dst] + src) % _M
            elif op == "SUB":
                regs[dst] = (regs[dst] - src) % _M
            elif op == "MUL":
                regs[dst] = (regs[dst] * src) % _M
        pc += 1
```
""",
    # Two violations, both of them plausible readings of a real machine: the flag
    # is consumed rather than persistent, and ROT rotates the other way. Every
    # opcode, every stop reason and the wraparound are still right, so this lands
    # in the middle of the range rather than at zero.
    wrong="""
```python
_M = 1 << 64


def run(program, max_steps):
    regs = [0, 0, 0, 0]
    flag = 0
    pc = 0
    steps = 0
    n = len(program)

    def value(operand):
        if operand[0] == "r":
            return regs[int(operand[1:])]
        return int(operand[1:]) % _M

    def result(reason):
        return {"regs": regs, "flag": flag, "pc": pc, "steps": steps, "reason": reason}

    while True:
        if pc < 0 or pc >= n:
            return result("fell_off")
        if steps >= max_steps:
            return result("step_limit")
        ins = program[pc]
        op = ins[0]
        steps += 1
        if op == "HALT":
            return result("halt")
        if op in ("JMP", "JIF"):
            if op == "JIF":
                taken = flag == 1
                flag = 0
                if not taken:
                    pc += 1
                    continue
            target = pc + ins[1]
            if target < 0 or target >= n:
                return result("bad_jump")
            pc = target
            continue
        if op == "CMP":
            flag = 1 if value(ins[1]) < value(ins[2]) else 0
        elif op == "ROT":
            regs = [regs[3], regs[0], regs[1], regs[2]]
        else:
            dst = int(ins[1][1:])
            src = value(ins[2])
            if op == "SET":
                regs[dst] = src
            elif op == "ADD":
                regs[dst] = (regs[dst] + src) % _M
            elif op == "SUB":
                regs[dst] = (regs[dst] - src) % _M
            elif op == "MUL":
                regs[dst] = (regs[dst] * src) % _M
        pc += 1
```
""",
)
