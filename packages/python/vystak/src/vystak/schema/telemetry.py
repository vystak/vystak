"""Telemetry resource schema — declares OpenTelemetry collector backing.

Per-platform config that drives provisioning of an OTel collector +
tracer init in agent and channel runtimes. The container runs a
single shared collector (currently Jaeger all-in-one) that all agents
+ channels on the same platform export OTLP traces to.

When ``enabled`` is True and ``endpoint`` is None, the provider
auto-provisions a collector container. When ``endpoint`` is set, no
container is provisioned — the agents/channels export to the
externally-managed collector at that URL.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Telemetry(BaseModel):
    """Per-platform telemetry config.

    Drives provisioning of an OTel collector container and tracer init
    in agent + channel runtimes. Only ``type='jaeger'`` is supported
    today; future values may include ``'tempo'`` or ``'external'``.
    """

    type: Literal["jaeger"] = "jaeger"
    enabled: bool = True
    endpoint: str | None = None
