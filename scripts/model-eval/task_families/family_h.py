from task_registry import CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# H - structured output with interdependent fields
# --------------------------------------------------------------------------

task(
    id="policy_json",
    group="H",
    kind="code",
    prompt=(
        "Emit a single JSON object, and nothing else, describing this retention policy.\n\n"
        "Source data:\n\n"
        "```\n"
        "bucket,days,records\n"
        "sessions,1,412\n"
        "usage,180,690\n"
        "audit,300,301\n"
        "transcripts,30,84\n"
        "```\n\n"
        "The policy window runs from 2026-03-01 to 2026-03-31.\n\n"
        "Rules:\n\n"
        "- The top-level object has the keys `policy_id`, `window`, `buckets`, `total_records`, "
        "and — only under the condition below — `review`.\n"
        "- `policy_id` is the string `RET-2026-03`.\n"
        "- `window` is an object with `starts_on` and `ends_on`, both `YYYY-MM-DD` strings, and "
        "`ends_on` must be strictly later than `starts_on`.\n"
        "- `buckets` is an array of objects with keys `name`, `days`, `records`, one per row of "
        "the source data, in the order given.\n"
        "- `total_records` is an integer and must equal the sum of the `records` fields of "
        "`buckets`.\n"
        "- `review` is an object with a single key `reason` (any string). It must be present if "
        "and only if at least one bucket has `days` greater than 365. If no bucket does, the "
        "`review` key must be absent entirely.\n\n"
        "Return exactly one fenced code block containing the JSON object and nothing else."
        + CODE_SUFFIX.replace("Python code block", "code block").replace(
            "the complete implementation", "the JSON object"
        )
    ),
    kind_hint="json",
    checks=[
        ("parses as one JSON object", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert isinstance(_o, dict), type(_o)
""", 10),
        ("policy_id", """
import json as _j
assert _j.loads(_PAYLOAD)["policy_id"] == "RET-2026-03"
""", 10),
        ("window dates ordered and correct", """
import json as _j
_w = _j.loads(_PAYLOAD)["window"]
assert _w["starts_on"] == "2026-03-01" and _w["ends_on"] == "2026-03-31", _w
assert _w["ends_on"] > _w["starts_on"]
""", 10),
        ("buckets match the source", """
import json as _j
_b = _j.loads(_PAYLOAD)["buckets"]
assert [(x["name"], x["days"], x["records"]) for x in _b] == [
    ("sessions", 1, 412), ("usage", 180, 690), ("audit", 300, 301), ("transcripts", 30, 84)
], _b
""", 10),
        ("total equals the sum of its parts", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert _o["total_records"] == 1487, _o["total_records"]
assert _o["total_records"] == sum(x["records"] for x in _o["buckets"])
""", 10),
        ("review absent because no bucket exceeds 365 days", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert "review" not in _o, "the longest bucket is 300 days, so review must be absent entirely"
""", 10),
        ("no extra top-level keys", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert set(_o) == {"policy_id", "window", "buckets", "total_records"}, sorted(_o)
""", 10),
    ],
    reference='''```json
{"policy_id": "RET-2026-03",
 "window": {"starts_on": "2026-03-01", "ends_on": "2026-03-31"},
 "buckets": [{"name": "sessions", "days": 1, "records": 412},
             {"name": "usage", "days": 180, "records": 690},
             {"name": "audit", "days": 300, "records": 301},
             {"name": "transcripts", "days": 30, "records": 84}],
 "total_records": 1487}
```''',
    wrong='''```json
{"policy_id": "RET-2026-03",
 "window": {"starts_on": "2026-03-01", "ends_on": "2026-03-31"},
 "buckets": [{"name": "sessions", "days": 1, "records": 412},
             {"name": "usage", "days": 180, "records": 690},
             {"name": "audit", "days": 300, "records": 301},
             {"name": "transcripts", "days": 30, "records": 84}],
 "total_records": 1487,
 "review": {"reason": "audit retention is long"}}
```''',
)

task(
    id="csv_reconcile",
    group="H",
    kind="code",
    prompt=(
        "Two systems disagree. Reconcile them and emit a single JSON object.\n\n"
        "Invoiced:\n"
        "```\n"
        "tenant,amount\n"
        "cinder,4120\n"
        "acme,9310\n"
        "borealis,2255\n"
        "dovetail,780\n"
        "```\n\n"
        "Metered:\n"
        "```\n"
        "tenant,amount\n"
        "acme,9310\n"
        "borealis,2401\n"
        "cinder,3998\n"
        "acme,140\n"
        "elm,1500\n"
        "```\n\n"
        "Rules:\n\n"
        "- A tenant may appear on more than one line of a table. Its amount in that table is the "
        "sum of its lines.\n"
        "- Include a row only for a tenant that appears in **both** tables. A tenant in only one "
        "table is excluded entirely.\n"
        "- The top-level object has exactly the keys `rows` and `total_delta`.\n"
        "- `rows` is an array of objects with exactly the keys `tenant`, `invoiced`, `metered`, "
        "`delta`, sorted by `tenant` ascending.\n"
        "- `delta` is `invoiced` minus `metered`.\n"
        "- `total_delta` is the sum of every `delta` in `rows`.\n"
        "- All amounts are integers.\n\n"
        "Return exactly one fenced code block containing the JSON object and nothing else."
        + CODE_SUFFIX.replace("Python code block", "code block").replace(
            "the complete implementation", "the JSON object"
        )
    ),
    kind_hint="json",
    checks=[
        ("parses, exactly two top-level keys", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert set(_o) == {"rows", "total_delta"}, sorted(_o)
""", 10),
        ("only tenants in both tables", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert [r["tenant"] for r in _o["rows"]] == ["acme", "borealis", "cinder"], _o["rows"]
""", 10),
        ("row keys exact", """
import json as _j
_o = _j.loads(_PAYLOAD)
for _r in _o["rows"]:
    assert set(_r) == {"tenant", "invoiced", "metered", "delta"}, sorted(_r)
""", 10),
        ("the repeated line is summed before the join", """
import json as _j
_o = _j.loads(_PAYLOAD)
_by = {r["tenant"]: r for r in _o["rows"]}
assert (_by["acme"]["invoiced"], _by["acme"]["metered"], _by["acme"]["delta"]) == (9310, 9450, -140), _by["acme"]
""", 10),
        ("deltas computed", """
import json as _j
_o = _j.loads(_PAYLOAD)
_by = {r["tenant"]: r for r in _o["rows"]}
assert (_by["borealis"]["invoiced"], _by["borealis"]["metered"], _by["borealis"]["delta"]) == (2255, 2401, -146)
assert (_by["cinder"]["invoiced"], _by["cinder"]["metered"], _by["cinder"]["delta"]) == (4120, 3998, 122)
""", 10),
        ("total_delta is the sum", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert _o["total_delta"] == -164, _o["total_delta"]
assert _o["total_delta"] == sum(r["delta"] for r in _o["rows"])
""", 10),
        ("integers, not strings", """
import json as _j
_o = _j.loads(_PAYLOAD)
for _r in _o["rows"]:
    for _k in ("invoiced", "metered", "delta"):
        assert isinstance(_r[_k], int), (_r["tenant"], _k, type(_r[_k]))
assert isinstance(_o["total_delta"], int)
""", 10),
    ],
    reference='''```json
{"rows": [{"tenant": "acme", "invoiced": 9310, "metered": 9450, "delta": -140},
          {"tenant": "borealis", "invoiced": 2255, "metered": 2401, "delta": -146},
          {"tenant": "cinder", "invoiced": 4120, "metered": 3998, "delta": 122}],
 "total_delta": -164}
```''',
    wrong='''```json
{"rows": [{"tenant": "acme", "invoiced": 9310, "metered": 9310, "delta": 0},
          {"tenant": "borealis", "invoiced": 2255, "metered": 2401, "delta": -146},
          {"tenant": "cinder", "invoiced": 4120, "metered": 3998, "delta": 122}],
 "total_delta": -24}
```''',
)
