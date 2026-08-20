"""Flat operations setting declarations."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class OperationsSettings(BaseSettings):
    host_metrics_url: str = "http://host.docker.internal:9101/host"
    """Where the launchd host-metrics agent answers.

    Loopback on the Mac, reached the same way as the runtimes, and for the same
    reason: a container on macOS reads a Linux VM's memory and disk, not the
    machine's. Optional infrastructure — an unreachable agent makes the panel
    say "not reporting" rather than failing a request."""

    retention_sweep_interval_seconds: int = 24 * 3600
    """How often stored retention windows are applied.

    A day rather than an hour: retention is measured in months, so sweeping
    more often deletes the same rows no sooner, and being a day late costs a
    day of rows that were already past their window. Zero or negative disables
    the loop, which is how a deployment opts out of automatic deletion while
    keeping the manual purge."""

    metrics_enabled: bool = True
    """Whether each application exposes `/metrics` for Prometheus. On by default;
    an operator who runs no Prometheus can turn it off, which also lifts the
    production requirement below that its scrape token be a real value."""

    metrics_scrape_token: str = Field(default="dev-metrics-token-not-for-production")
    """Bearer token Prometheus presents to `/metrics`. A secret, so it is a file
    mount like the rest; required to be a real value in production only when
    `metrics_enabled` is set. See interfaces/http/routers/metrics.py."""
