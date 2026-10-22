"""The LaunchDaemon plists are templates that render to valid plists.

`launchd/install-daemons.sh` substitutes `@OPERATOR@` and `@REPO@` with sed and
lints with `plutil`, which CI's Linux runner does not have; this renders the
same way in Python so a broken template fails here rather than on the host.
It also holds the reason they are templates: the repository is public, so no
file under `launchd/` may name a home directory other than `/Users/Shared`,
nor a mailbox: the health check's recipients are read from `secrets/alert_to`.
"""

import plistlib
import re
from pathlib import Path

import pytest

LAUNCHD = Path(__file__).resolve().parents[3] / "launchd"
TEMPLATES = sorted(LAUNCHD.glob("online.rcsl.*.plist"))
PLACEHOLDER = re.compile(r"@[A-Z_]+@")
HOME_PATH = re.compile(r"/Users/(?!Shared\b)[A-Za-z0-9_.-]+")
MAILBOX = re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b)[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")


def _render(text: str) -> str:
    return text.replace("@OPERATOR@", "operator").replace("@REPO@", "/opt/nexus")


def test_there_are_templates() -> None:
    assert TEMPLATES, LAUNCHD


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_a_template_renders_to_a_valid_plist(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert set(PLACEHOLDER.findall(text)) <= {"@OPERATOR@", "@REPO@"}
    rendered = _render(text)
    assert not PLACEHOLDER.search(rendered)
    parsed = plistlib.loads(rendered.encode())
    assert parsed["Label"] == path.stem


def test_the_installer_substitutes_every_placeholder_the_templates_use() -> None:
    script = (LAUNCHD / "install-daemons.sh").read_text(encoding="utf-8")
    used = {m for p in TEMPLATES for m in PLACEHOLDER.findall(p.read_text(encoding="utf-8"))}
    for placeholder in used:
        assert f"s|{placeholder}|" in script, placeholder


def test_nothing_under_launchd_names_a_home_directory() -> None:
    found = [
        f"{p.relative_to(LAUNCHD)}: {m}"
        for p in sorted(LAUNCHD.rglob("*"))
        if p.is_file() and p.suffix in {".plist", ".sh", ".py"}
        for m in HOME_PATH.findall(p.read_text(encoding="utf-8"))
    ]
    assert not found, found


def test_nothing_under_launchd_names_a_mailbox() -> None:
    found = [
        f"{p.relative_to(LAUNCHD)}: {m}"
        for p in sorted(LAUNCHD.rglob("*"))
        if p.is_file() and p.suffix in {".plist", ".sh", ".py"}
        for m in MAILBOX.findall(p.read_text(encoding="utf-8"))
    ]
    assert not found, found
