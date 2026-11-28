"""Which test environment EvidenceTrail investigates.

TARGET=shopsim  (default) our own 9-service ShopSim on Docker Compose.
TARGET=oteldemo the OpenTelemetry Demo (Astronomy Shop, Apache-2.0, run separately),
                with faults injected through its flagd feature flags.
"""
from __future__ import annotations

import os

TARGET = os.environ.get("TARGET", "shopsim").strip().lower()
if TARGET not in ("shopsim", "oteldemo"):
    raise ValueError(f"TARGET must be 'shopsim' or 'oteldemo', not {TARGET!r}")
OTEL = TARGET == "oteldemo"
