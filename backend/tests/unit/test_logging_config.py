"""The application's own INFO lines have to reach the log.

This pins a defect that existed from the first deploy until 2026-08-03 and was
invisible in exactly the way that made it expensive: nothing configured
logging, so the root logger had no handler, Python's `lastResort` fallback took
every record, and that handler emits at WARNING. Every `logger.info` in the
tree was discarded.

The line that mattered is `perimeter_rejected` in `geo_middleware`, which is
the only place the three causes of a `400 untrusted_proxy` are distinguished —
the response deliberately distinguishes none of them. Diagnosing a real one
took probing the deployment from outside with wrong values until the answers
narrowed it down.

So the assertions here are about the level rather than about formatting: that
an `app.*` logger is enabled for INFO, that the setting can still turn it down,
and that the root is left alone so `httpx` does not start logging every request
to the model runtime.
"""

from __future__ import annotations

import logging

from app.infrastructure.config import Settings
from app.infrastructure.logging_config import APP_LOGGER, configure_logging

# The real caller, spelled out rather than a placeholder: this is the logger
# whose silence the module exists to fix.
PERIMETER_LOGGER = "app.interfaces.http.middleware.geo_middleware"


def test_app_loggers_are_enabled_for_info() -> None:
    """The regression itself. Under the old behaviour this was False."""
    configure_logging(Settings(env="development", auth_mode="dev"))

    assert logging.getLogger(PERIMETER_LOGGER).isEnabledFor(logging.INFO)


def test_perimeter_rejection_actually_reaches_a_handler() -> None:
    """Enabled is not the same as delivered, so follow the record through."""
    configure_logging(Settings(env="development", auth_mode="dev"))
    logger = logging.getLogger(PERIMETER_LOGGER)

    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    capture = Capture()
    logger.addHandler(capture)
    try:
        logger.info(
            "perimeter_rejected path=%s code=%s detail=%s",
            "/admin/me",
            "untrusted_proxy",
            "proxy secret missing or wrong",
        )
    finally:
        logger.removeHandler(capture)

    assert len(records) == 1
    # The detail is the whole point: it is what separates a wrong secret from
    # an absent X-Forwarded-For, which the 400 response will not say.
    assert "proxy secret missing or wrong" in records[0].getMessage()


def test_level_remains_configurable() -> None:
    configure_logging(Settings(env="development", auth_mode="dev", log_level="WARNING"))

    logger = logging.getLogger(PERIMETER_LOGGER)
    assert not logger.isEnabledFor(logging.INFO)
    assert logger.isEnabledFor(logging.WARNING)


def test_lowercase_level_is_accepted() -> None:
    """`.env` files are written by people, and `info` is what people type."""
    configure_logging(Settings(env="development", auth_mode="dev", log_level="info"))

    assert logging.getLogger(PERIMETER_LOGGER).isEnabledFor(logging.INFO)


def test_repeated_configuration_does_not_multiply_handlers() -> None:
    """`create_app` runs more than once in a test session."""
    settings = Settings(env="development", auth_mode="dev")
    configure_logging(settings)
    configure_logging(settings)
    configure_logging(settings)

    assert len(logging.getLogger(APP_LOGGER).handlers) == 1


def test_third_party_loggers_are_left_alone() -> None:
    """Deliberate: raising the root would put an `httpx` line on the hot path.

    One per request to the model runtime, saying nothing `usage_records` does
    not already hold.
    """
    configure_logging(Settings(env="development", auth_mode="dev"))

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
