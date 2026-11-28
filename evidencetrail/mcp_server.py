"""EvidenceTrail as an MCP server.

Lets Claude (Claude Code / Claude Desktop), Gemini CLI or any MCP client investigate
incidents with EvidenceTrail's read-only telemetry tools and its evidence-gated
Gemini investigation. Read-only by design: no fault injection, no actions.

Run (stdio):            python -m evidencetrail.mcp_server
Claude Code:            claude mcp add evidencetrail -- python -m evidencetrail.mcp_server
Streamable HTTP:        python -m evidencetrail.mcp_server --http 8765
"""
from __future__ import annotations

import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .investigator import Investigation, suspects
from .telemetry import Telemetry, make_telemetry

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

mcp = MCPServer(
    name="evidencetrail",
    title="EvidenceTrail",
    description="Evidence-backed incident investigation for cloud-native systems, powered by Google Gemini.",
    instructions=(
        "Use these tools to investigate an incident in the EvidenceTrail test environment. "
        "Start with get_service_health and get_suspects, then fetch evidence (logs, traces, metrics, changes). "
        "Every claim you make should cite an evidence_id returned by a tool. "
        "investigate runs the full Gemini investigation with the evidence gate and returns a verified diagnosis."),
    version="1.0.0",
)


def _tel(window_s: int) -> Telemetry:
    return make_telemetry(window_s=max(30, min(window_s, 1800)))


@mcp.tool(annotations=READ_ONLY)
def get_service_health(window_s: int = 120) -> dict:
    """Per-service request rate, error ratio and p95 latency now vs a baseline window (Prometheus)."""
    return _tel(window_s).service_health()


@mcp.tool(annotations=READ_ONLY)
def get_suspects(window_s: int = 120) -> list[dict]:
    """Anomalous services ranked by the call graph: 'deepest' suspects have no anomalous dependencies,
    so they are likely causes; their callers are likely victims."""
    t = _tel(window_s)
    return suspects(t.service_health(), t.dependency_graph()["edges"])


@mcp.tool(annotations=READ_ONLY)
def get_logs(service: str, level: str = "ERROR", contains: str = "", window_s: int = 120) -> dict:
    """Grouped log lines for a service (most frequent first), secrets redacted. Each group has an evidence_id."""
    return _tel(window_s).logs(service, level, contains or None)


@mcp.tool(annotations=READ_ONLY)
def get_metric(service: str, name: str, window_s: int = 300) -> dict:
    """A metric time series for a service. ShopSim: error_ratio, p95_latency_ms, request_rate, heap_mb,
    db_pool_in_use, config_version, dependency_errors or up. OpenTelemetry Demo: error_ratio,
    p95_latency_ms, request_rate, dependency_errors, cpu_percent or memory_mb."""
    return _tel(window_s).metric(service, name)


@mcp.tool(annotations=READ_ONLY)
def get_error_traces(service: str, window_s: int = 120) -> dict:
    """Failing traces through a service, reduced to the chain of failing spans (deepest = closest to the cause)."""
    return _tel(window_s).error_traces(service)


@mcp.tool(annotations=READ_ONLY)
def get_recent_changes(window_s: int = 900) -> dict:
    """Deployments and configuration changes in the lookback period."""
    return _tel(window_s).changes(lookback_s=window_s)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def investigate(alert: str, window_s: int = 120, engine: str = "native") -> dict:
    """Run a full EvidenceTrail investigation (Gemini + evidence gate). engine: 'native' or 'adk' (Google ADK).
    Returns the verdict (DIAGNOSIS / INCONCLUSIVE / FAILED), root cause, fault type, claims that survived the
    evidence gate with their evidence, blocked claims, and a policy-labelled suggested action (never executed)."""
    r = Investigation(alert, window_s=window_s, engine=engine if engine in ("native", "adk") else "native").run()
    keep = ("verdict", "root_cause_service", "fault_type", "confidence", "summary", "ranked_candidates", "claims",
            "dropped_claims", "evidence_precision", "rejected_hypotheses", "suggested_action", "elapsed_s", "usage", "model", "engine")
    return {k: r.get(k) for k in keep}


if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1]) if len(sys.argv) > sys.argv.index("--http") + 1 else 8765
        mcp.run(transport="streamable-http", port=port)
    else:
        mcp.run()
