"""The public admin entrance must never let a Tailscale identity header through.

The tailnet application trusts `Tailscale-User-Login` outright, so if one
survives on this entrance the result is a full administrator bypass from the
open internet. nginx clears these headers too; this test covers the inner
layer, which is the one that still holds if the proxy config is edited by
someone who does not know why those lines are there.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.infrastructure.main_admin_public import StripTailscaleHeadersMiddleware


def build_echo_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(StripTailscaleHeadersMiddleware)

    @app.get("/echo")
    async def echo(request: Request) -> dict[str, list[str]]:
        return {"headers": sorted(k.lower() for k in request.headers)}

    return app


def test_tailscale_headers_are_removed() -> None:
    client = TestClient(build_echo_app())
    response = client.get(
        "/echo",
        headers={
            "Tailscale-User-Login": "attacker@example.com",
            "Tailscale-User-Name": "Attacker",
        },
    )
    seen = response.json()["headers"]
    assert not [h for h in seen if h.startswith("tailscale-")]


def test_stripping_is_case_insensitive() -> None:
    client = TestClient(build_echo_app())
    response = client.get("/echo", headers={"TAILSCALE-USER-LOGIN": "attacker@example.com"})
    seen = response.json()["headers"]
    assert not [h for h in seen if h.startswith("tailscale-")]


def test_unrelated_headers_survive() -> None:
    client = TestClient(build_echo_app())
    response = client.get("/echo", headers={"X-Request-Id": "abc"})
    assert "x-request-id" in response.json()["headers"]
