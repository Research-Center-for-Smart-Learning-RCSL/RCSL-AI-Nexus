"""`Cache-Control: no-store`, and the two things it must not do.

The header itself is one line; the tests are about the edges. It must not
overwrite a response that chose its own value — `sse.py` and `qr.py` both did,
deliberately — and it has to reach the responses nobody writes a handler for,
which is the ones a rejecting perimeter middleware builds. A middleware that
covered only the happy path would leave exactly the responses with the most to
say about a caller uncovered.

See middleware/cache_control.py for why the header is wanted at all, and
security.md §15.1 and §15.2 for the intermediary in the path.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

from app.infrastructure.config import get_settings
from app.infrastructure.main_admin_public import create_app as create_admin_public
from app.infrastructure.main_admin_tailnet import create_app as create_admin_tailnet
from app.infrastructure.main_gateway import create_app as create_gateway
from app.interfaces.http.middleware.cache_control import CacheControlMiddleware


def _isolated() -> FastAPI:
    app = FastAPI()

    @app.get("/plain")
    async def plain() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/chose-no-cache")
    async def chose_no_cache() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            yield b"data: hello\n\n"

        return StreamingResponse(
            body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/chose-lowercase")
    async def chose_lowercase() -> PlainTextResponse:
        return PlainTextResponse("ok", headers={"cache-control": "no-store, private"})

    app.add_middleware(CacheControlMiddleware)
    return app


def test_a_response_that_says_nothing_is_told_not_to_be_stored() -> None:
    response = TestClient(_isolated()).get("/plain")
    assert response.headers["cache-control"] == "no-store"


def test_a_response_that_chose_its_own_value_keeps_it() -> None:
    """The stream case, and the reason this is not merely tidiness: `no-cache`
    and `no-store` are not interchangeable in how intermediaries treat a
    stream, so widening one is a decision rather than an improvement."""
    response = TestClient(_isolated()).get("/chose-no-cache")
    assert response.headers["cache-control"] == "no-cache"


def test_an_existing_header_is_matched_case_insensitively() -> None:
    """A second `Cache-Control` line would leave the intermediary to choose,
    which is the one outcome worse than saying nothing."""
    response = TestClient(_isolated()).get("/chose-lowercase")
    assert response.headers["cache-control"] == "no-store, private"
    assert len(response.headers.get_list("cache-control")) == 1


APPS = {
    "gateway": create_gateway,
    "admin-tailnet": create_admin_tailnet,
    "admin-public": create_admin_public,
}


@pytest.fixture(params=sorted(APPS), ids=sorted(APPS))
def app(request: pytest.FixtureRequest) -> FastAPI:
    get_settings.cache_clear()
    return APPS[request.param]()


def test_every_entrance_installs_it(app: FastAPI) -> None:
    """The wiring, not the middleware: three applications compose their stacks
    in three files, and a header added to two of them is the shape of gap this
    repository keeps finding."""
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_a_perimeter_rejection_carries_it_too() -> None:
    """CSRF refuses an unsafe method with no token, in middleware, before any
    handler and before any dependency. That response is built by the perimeter
    rather than by a route, and it is exactly the sort worth not storing.

    The tailnet entrance rather than the public one: the public entrance's geo
    filter reads `app.state`, which the lifespan populates, so an unstarted
    application fails there for a reason that has nothing to do with this.
    """
    get_settings.cache_clear()
    response = TestClient(create_admin_tailnet()).post("/admin/users")
    assert response.status_code >= 400
    assert response.headers["cache-control"] == "no-store"
