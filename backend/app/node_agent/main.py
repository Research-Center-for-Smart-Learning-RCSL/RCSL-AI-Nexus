"""`uvicorn app.node_agent.main:app --workers 1` — one process, never forked.

One worker and no reload: a second worker would be a second process trying
to take the same host lock, and uvicorn's reloader forks.
"""

from __future__ import annotations

from app.node_agent.api import create_app

app = create_app()
