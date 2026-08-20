#!/usr/bin/env python3
"""Can a local model actually drive an agent loop?

A ladder, simplest first. Each rung isolates one thing that has to work before
the next is even meaningful, so a failure names *which* ability is missing
rather than reporting that the agent did not finish.

    NEXUS_API_KEY=nx_live_... scripts/measure-agent-loop.py 10
    NEXUS_API_KEY=nx_live_... scripts/measure-agent-loop.py all

The rungs: 1 emit a call, 2 fill an argument, 3 complete the round trip,
4 choose between two tools, 5 chain two calls, 6 decline to call when the
question needs no tool, 7 two calls in one turn, 8 recover from a tool error,
9 choose from a menu of eight, 10 the real shape — read failing tests, find
the bug, fix the source, re-run to confirm.

Environment:

    NEXUS_API_KEY      required; a key scoped to the capability below
    NEXUS_MODEL        the *capability*, not a model name (default: chat)
    NEXUS_THINK        true/false to override deliberation per request.
                       Unset asks for nothing, so the routing policy decides,
                       which is what a real client does. Set it to measure what
                       deliberation costs: an agent pays it again on every tool
                       round trip rather than once per conversation.
    NEXUS_GATEWAY      base URL. Defaults to TAILNET_IP from .env on port 8000,
                       because the gateway publishes on the tailnet address and
                       never on loopback or 0.0.0.0
    NEXUS_PROXY_SECRET  } see below; both default to reading ./secrets
    NEXUS_CLIENT_IP    an address the country filter allows (default: a TW one)

Standing in for the proxy is not optional. Under ENV=production the gateway
requires the shared-secret header and refuses to fall back to the peer address
for `X-Forwarded-For`, so a request straight from the host is a 400
`untrusted_proxy`. That is the perimeter working; this supplies both headers
the way openresty would.
"""

from __future__ import annotations

import sys

from agent_loop.runner import main as _main


def main(argv: list[str]) -> None:
    """Run the selected measurement rung through the stable script facade."""
    _main(argv, help_text=__doc__)

if __name__ == "__main__":
    main(sys.argv)
