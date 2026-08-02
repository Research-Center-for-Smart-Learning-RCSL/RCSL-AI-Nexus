"""Carrying the resolved actor on the request, for the error handler.

The actor is produced by a dependency, which means it exists only inside the
handler's arguments. The exception handler runs after that frame is gone and
still needs to say *who* was refused, so each resolver leaves a copy here on
its way past.

Deliberately not a general-purpose "current user" accessor. Nothing should read
this to make a decision: authorization is decided from the `Actor` a use case
was given, in the use case, which is the rule section 5.2 exists to keep. This
is for recording what already happened.
"""

from __future__ import annotations

from starlette.requests import Request

from app.domain.entities.actor import Actor

ACTOR_STATE_KEY = "nexus_actor"


def remember_actor(request: Request, actor: Actor) -> Actor:
    """Called by each resolver. Returns the actor so it can be used inline."""
    setattr(request.state, ACTOR_STATE_KEY, actor)
    return actor


def actor_from_request(request: Request) -> Actor | None:
    """None when the request never got as far as being identified, which is
    every 401 and anything rejected by middleware ahead of the resolver."""
    return getattr(request.state, ACTOR_STATE_KEY, None)
