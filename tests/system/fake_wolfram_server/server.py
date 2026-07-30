"""Test-only standalone fake Wolfram MCP server (Slice 2B Batch B packet §5).

A CONTROLLED science backend, NOT the real Wolfram Cloud MCP. Exposes the
allowlisted ``WolframAlpha`` and ``WolframContext`` Tools over MCP Streamable
HTTP so the REAL product science MCP client (``science_tool_service`` and
``tutor_generation._execute_science_tool_call``) connects, verifies
protocol/allowlist/schema, calls a Tool and receives a bounded observation.

Faithfulness notes (packet §5 / §6):
- The real Wolfram server is an older MCP server that advertises protocol
  ``2025-03-26``. The installed MCP SDK (1.28.x) defaults to ``2025-11-25``. To
  faithfully mimic the real remote's contract this fake pins the negotiated
  protocol to ``2025-03-26`` by patching the SDK's version selection **in this
  fake server process only**. No product code is changed; the product's science
  path requires ``2025-03-26``.
- NEVER exposes ``WolframLanguageEvaluator`` (forbidden by the product allowlist).
- Reset/counters are atomic under one lock; endpoints return ONLY the scenario,
  the call count and a stable classification — never request bodies, expressions,
  observations, keys or URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any

# --- Protocol pin (fake server process only; faithful to real older Wolfram) ---
import mcp.server.session as _server_session  # type: ignore
import mcp.types as _mcp_types  # type: ignore

# Force the server's negotiated version into the else-branch and set LATEST to
# the Wolfram-pinned version. The client requests 2025-11-25; not in the (empty)
# supported set -> server returns LATEST = 2025-03-26. The client accepts it
# (2025-03-26 is in the client SDK's supported set).
_server_session.SUPPORTED_PROTOCOL_VERSIONS = set()  # type: ignore[attr-defined]
_mcp_types.LATEST_PROTOCOL_VERSION = "2025-03-26"  # type: ignore[attr-defined]

from mcp.server import Server
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool

PORT = int(os.environ.get("FAKE_WOLFRAM_PORT", "8120"))

LOCK = threading.Lock()
ACTIVE_SCENARIO = "success"
COUNTS: dict[str, int] = {}

# Fixed tool schemas (deterministic; the probe hashes these to form the
# capability projection's verified_schema_hash, which the live call re-verifies).
# The product normalizes the legacy "input" alias to Wolfram's CURRENT "query"
# contract (science_tool_service.normalize_science_arguments), so the callable
# contract requires "query"; "input" is kept as an optional legacy alias.
WOLFRAM_ALPHA_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Wolfram Alpha query string"},
        "input": {"type": "string", "description": "Legacy query alias"},
        "podstate": {"type": "string", "description": "Optional pod state"},
    },
    "required": ["query"],
}
WOLFRAM_ALPHA_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {"type": "string"},
        "pods": {"type": "array", "items": {"type": "object"}},
    },
}
WOLFRAM_CONTEXT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Context query"},
        "context": {"type": "string", "description": "Context string"},
    },
    "required": ["query"],
}
WOLFRAM_CONTEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"result": {"type": "string"}},
}


def _observation_for(scenario: str, tool: str, arguments: dict[str, Any]) -> str:
    """Return the TextContent JSON for a tool call, by scenario.

    success       -> a bounded, verified observation (Practice sees verified=True).
    invalid_result-> a payload with no verified flag (Practice classifies the
                     reference as unverified / tool_result_invalid).
    """
    if scenario == "invalid_result":
        # No verified/equivalent key and not a stable error code; parse_science
        # yields {"text": ...} -> Practice science sees unverified.
        return json.dumps({"value": "unverified_payload"})
    # success
    return json.dumps({"verified": True, "equivalent": True, "result": "controlled"})


server = Server("wolfram-cloud-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    # No outputSchema: the real Wolfram Tools (and the product's allowlisted
    # hash contract) only pin inputSchema; output is a bounded text observation.
    # The probe/live call hash outputSchema as {} consistently.
    return [
        Tool(
            name="WolframAlpha",
            description="Wolfram Alpha computational knowledge engine",
            inputSchema=WOLFRAM_ALPHA_INPUT_SCHEMA,
        ),
        Tool(
            name="WolframContext",
            description="Wolfram contextual computation",
            inputSchema=WOLFRAM_CONTEXT_INPUT_SCHEMA,
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    with LOCK:
        COUNTS[ACTIVE_SCENARIO] = COUNTS.get(ACTIVE_SCENARIO, 0) + 1
        scenario = ACTIVE_SCENARIO
    # Never serve the forbidden tool name.
    if name == "WolframLanguageEvaluator":
        return [TextContent(type="text", text=json.dumps({"error": "tool_not_allowed"}))]
    if name not in ("WolframAlpha", "WolframContext"):
        return [TextContent(type="text", text=json.dumps({"error": "tool_not_found"}))]
    return [TextContent(type="text", text=_observation_for(scenario, name, arguments or {}))]


# ---------------------------------------------------------------------------
# ASGI app: Streamable HTTP MCP (/mcp) + safe control endpoints.
# ---------------------------------------------------------------------------

session_manager = StreamableHTTPSessionManager(
    server,
    security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
mcp_app = StreamableHTTPASGIApp(session_manager)
_session_run: dict[str, Any] = {}


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [[b"content-type", b"application/json"]]})
    await send({"type": "http.response.body", "body": body})


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                try:
                    _session_run["v"] = session_manager.run()
                    await _session_run["v"].__aenter__()
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                if _session_run.get("v") is not None:
                    await _session_run["v"].__aexit__(None, None, None)
                await send({"type": "lifespan.shutdown.complete"})
                return
        return

    if scope["type"] != "http":
        return

    path = scope.get("path", "")
    method = scope.get("method", "")
    if path == "/readyz" and method == "GET":
        await _send_json(send, 200, {"ready": True, "reason_code": "ok"})
        return
    if path.startswith("/__calls/") and method == "GET":
        scenario = path.rsplit("/", 1)[-1]
        with LOCK:
            count = COUNTS.get(scenario, 0)
        await _send_json(send, 200, {"scenario": scenario, "count": count})
        return
    if path == "/__reset" and method == "POST":
        global ACTIVE_SCENARIO
        length = int(next((h[1] for h in scope.get("headers", []) if h[0] == b"content-length"), b"0"))
        raw = await receive()
        body = raw.get("body", b"") if raw else b""
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            payload = {}
        scenario = str(payload.get("scenario", "success"))
        with LOCK:
            ACTIVE_SCENARIO = scenario
            COUNTS[scenario] = 0
        await _send_json(send, 200, {"scenario": scenario, "count": 0})
        return
    # Default: the MCP Streamable HTTP endpoint.
    await mcp_app(scope, receive, send)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
