"""Deterministic long specification used by evaluation group E."""

from spec_sections.data_lifecycle import DATA_LIFECYCLE_SECTIONS
from spec_sections.foundation import FOUNDATION_SECTIONS
from spec_sections.operations import OPERATIONS_SECTIONS

CONTRADICTION = ("3.7", "11.6")
PRECEDENCE_ANSWER = "9.8"

def sections() -> list[tuple[int, str, list[str]]]:
    return [
        *FOUNDATION_SECTIONS,
        *DATA_LIFECYCLE_SECTIONS,
        *OPERATIONS_SECTIONS,
    ]

def render() -> str:
    out = ["DATA RETENTION AND ACCESS POLICY", "Revision 2026-03, numbered clauses.", ""]
    for number, title, clauses in sections():
        out.append(f"{number}. {title}")
        for index, body in enumerate(clauses, start=1):
            out.append(f"  {number}.{index} {body}")
        out.append("")
    return "\n".join(out)

if __name__ == "__main__":
    document = render()
    print(document)
    print(f"\n--- {len(document)} chars, ~{len(document)//4} tokens", flush=True)
