"""The agent's side of the runtime supervisor (P3 on #61).

A request written, its receipt read and checked; a request the supervisor never
took is withdrawn on timeout, and one it took is reported as one that may still
run, never as withdrawn.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.node_agent.supervisor import Supervisor, SupervisorRefused


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    requests, receipts = tmp_path / "requests", tmp_path / "receipts"
    requests.mkdir()
    receipts.mkdir()
    return requests, receipts


async def answer_once(requests: Path, receipts: Path, **overrides: object) -> None:
    """The supervisor's part: claim the first request, write its receipt."""
    while True:
        found = [p for p in requests.iterdir() if p.name.endswith(".json")]
        if found:
            request = json.loads(found[0].read_text())
            found[0].rename(requests / f".{request['request_id']}.claimed")
            receipt = {"request_id": request["request_id"], "action": request["action"]}
            receipt |= {"result": "ok"} | overrides
            (receipts / found[0].name).write_text(json.dumps(receipt))
            return
        await asyncio.sleep(0.01)


async def test_a_request_is_answered_by_its_own_receipt(dirs: tuple[Path, Path]) -> None:
    requests, receipts = dirs
    supervisor = Supervisor(requests, receipts, timeout_s=2, poll_s=0.01)
    answering = asyncio.create_task(answer_once(requests, receipts))

    receipt = await supervisor.run("restart", "reset")
    await answering

    assert receipt["result"] == "ok"
    assert receipt["action"] == "restart"
    assert supervisor.receipt(receipt["request_id"]) == receipt


async def test_a_receipt_for_another_action_is_refused(dirs: tuple[Path, Path]) -> None:
    requests, receipts = dirs
    supervisor = Supervisor(requests, receipts, timeout_s=2, poll_s=0.01)
    answering = asyncio.create_task(answer_once(requests, receipts, action="stop"))

    with pytest.raises(SupervisorRefused, match="does not answer"):
        await supervisor.run("restart", "reset")
    await answering


async def test_an_untaken_request_is_withdrawn_on_timeout(dirs: tuple[Path, Path]) -> None:
    requests, receipts = dirs
    supervisor = Supervisor(requests, receipts, timeout_s=0.05, poll_s=0.01)

    with pytest.raises(SupervisorRefused, match="withdrawn") as refused:
        await supervisor.run("stop", "maintenance")

    assert refused.value.request_id is not None
    assert list(requests.iterdir()) == []


async def test_a_taken_request_without_a_receipt_may_still_run(dirs: tuple[Path, Path]) -> None:
    requests, receipts = dirs
    supervisor = Supervisor(requests, receipts, timeout_s=0.2, poll_s=0.01)

    async def claim_and_stall() -> None:
        while True:
            for path in requests.iterdir():
                if path.name.endswith(".json"):
                    path.rename(requests / f".{path.stem}.claimed")
                    return
            await asyncio.sleep(0.01)

    claiming = asyncio.create_task(claim_and_stall())
    with pytest.raises(SupervisorRefused, match="may still run"):
        await supervisor.run("stop", "maintenance")
    await claiming


async def test_only_the_three_fixed_actions_exist(dirs: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError):
        await Supervisor(*dirs).run("exec", "anything")


async def test_without_its_directories_the_supervisor_is_unavailable(tmp_path: Path) -> None:
    supervisor = Supervisor(tmp_path / "absent", tmp_path / "absent-too")
    assert not supervisor.available
    with pytest.raises(SupervisorRefused, match="not mounted"):
        await supervisor.run("restart", "reset")


async def test_a_named_request_asked_again_returns_its_receipt(dirs: tuple[Path, Path]) -> None:
    """The coordinator names its reset (P4): asking again after a timeout or
    an agent restart must return that restart's receipt, not restart again."""
    requests, receipts = dirs
    supervisor = Supervisor(requests, receipts, timeout_s=2, poll_s=0.01)
    named = "e" * 32
    answering = asyncio.create_task(answer_once(requests, receipts))

    first = await supervisor.run("restart", "maintenance", request_id=named)
    await answering
    again = await supervisor.run("restart", "maintenance", request_id=named)

    assert first == again and first["request_id"] == named
    assert [p.name for p in requests.iterdir() if p.name.endswith(".json")] == []


async def test_a_named_request_the_supervisor_holds_is_waited_for(dirs: tuple[Path, Path]) -> None:
    requests, receipts = dirs
    named = "f" * 32
    (requests / f".{named}.claimed").write_text("{}")  # taken, still running
    supervisor = Supervisor(requests, receipts, timeout_s=2, poll_s=0.01)

    async def finish() -> None:
        await asyncio.sleep(0.05)
        receipt = {"request_id": named, "action": "restart", "result": "ok"}
        (receipts / f"{named}.json").write_text(json.dumps(receipt))

    finishing = asyncio.create_task(finish())
    receipt = await supervisor.run("restart", "maintenance", request_id=named)
    await finishing

    assert receipt["result"] == "ok"
    assert not (requests / f"{named}.json").exists(), "never written a second time"


async def test_a_request_id_must_be_one_the_supervisor_accepts(dirs: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError):
        await Supervisor(*dirs).run("restart", "x", request_id="../../etc")


async def test_a_withdrawn_request_is_refused_and_never_runs(dirs: tuple[Path, Path]) -> None:
    """Review of #80: the agent withdraws a request the supervisor has not
    taken when the hold lifts; the call waiting on it ends at once."""
    requests, receipts = dirs
    supervisor = Supervisor(requests, receipts, timeout_s=5, poll_s=0.01)
    running = asyncio.create_task(supervisor.run("restart", "maintenance", request_id="1" * 32))
    await asyncio.sleep(0.05)

    assert supervisor.outstanding() == (["1" * 32], [])
    assert supervisor.withdraw("1" * 32)
    with pytest.raises(SupervisorRefused, match="withdrawn"):
        await asyncio.wait_for(running, 1)
    assert supervisor.outstanding() == ([], [])


async def test_a_taken_request_cannot_be_withdrawn_and_is_outstanding(
    dirs: tuple[Path, Path],
) -> None:
    requests, receipts = dirs
    (requests / f".{'2' * 32}.claimed").write_text("{}")
    supervisor = Supervisor(requests, receipts)

    assert not supervisor.withdraw("2" * 32)
    assert supervisor.outstanding() == ([], ["2" * 32])
    (receipts / f"{'2' * 32}.json").write_text(json.dumps({"request_id": "2" * 32}))
    assert supervisor.outstanding() == ([], []), "answered: no longer outstanding"
