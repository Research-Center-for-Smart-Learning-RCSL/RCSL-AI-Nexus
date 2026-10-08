"""The audited CLI that clears a node block (maintainer decision Q1 on #24).

    docker compose run --rm node-agent python -m app.node_agent.resolve status
    docker compose run --rm node-agent python -m app.node_agent.resolve start \
        --op <op_id> --operator <name> --evidence "<what you relied on>"
    #   ... restart the runtime ...
    docker compose run --rm node-agent python -m app.node_agent.resolve complete \
        --resolution <id>

Run through the agent's own service definition so it has the same volumes,
token and network. It never touches the database or the runtime itself: the
live agent, which holds the node's host lock, performs the resolution, and
refuses unless the ordered reset evidence holds (`resolution.py`). One
operation per invocation; there is no bulk form.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from app.infrastructure.config.core import SECRETS_DIR


def _token() -> str:
    try:
        return (SECRETS_DIR / "node_agent_token").read_text().strip()
    except OSError as exc:
        raise SystemExit(f"cannot read the agent token: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--agent", default=os.environ.get("NODE_AGENT_URL", "http://node-agent:8100")
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    begin = sub.add_parser("start")
    begin.add_argument("--op", required=True)
    begin.add_argument("--operator", required=True)
    begin.add_argument("--evidence", required=True)
    finish = sub.add_parser("complete")
    finish.add_argument("--resolution", required=True)
    args = parser.parse_args(argv)

    headers = {"Authorization": f"Bearer {_token()}"}
    # Resolution drains the agent and waits for the witness, so allow time.
    with httpx.Client(base_url=args.agent, headers=headers, timeout=600) as client:
        if args.command == "status":
            response = client.get("/v1/status")
        elif args.command == "start":
            response = client.post(
                "/v1/maintenance/resolutions",
                json={"op_id": args.op, "operator": args.operator, "evidence": args.evidence},
            )
        else:
            response = client.post(f"/v1/maintenance/resolutions/{args.resolution}/complete")
    print(json.dumps(response.json(), indent=2))
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
