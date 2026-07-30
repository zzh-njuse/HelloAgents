"""Shared science tool service — Wolfram MCP calls for Lesson, Practice, and Tutor.

Per ADR 006 §2.7: sends only minimal expressions to Wolfram.
Per ADR 006 §2.8: observations are NOT learning facts.
Per Spec 004 §5/§7: Lesson Writer and Practice may call Wolfram under Job authorization.
Per Correction 011 §2: fake MCP server is sufficient for implementation and testing.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from learn_platform_api.settings import Settings

# Fixed allowlist per ADR 006 §2.1
WOLFRAM_TOOL_WHITELIST = frozenset({"WolframAlpha", "WolframContext"})

# Stable error codes — never include raw exception text, remote body,
# endpoint URL, or internal IDs (per correction 005 §3.2).
STABLE_SCIENCE_ERRORS = frozenset({
    "protocol_drift", "tool_not_found", "tool_not_allowed",
    "tool_call_error", "empty_result", "non_json_result",
    "mcp_connection_failed", "schema_drift", "result_too_large",
    "capability_unavailable",
})


def normalize_science_arguments(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize the legacy ``input`` alias to Wolfram's current ``query`` contract."""
    normalized = dict(arguments)
    if tool in WOLFRAM_TOOL_WHITELIST and "query" not in normalized and set(normalized) == {"input"}:
        normalized = {"query": normalized["input"]}
    return normalized


def parse_science_text_content(raw_text: str) -> dict[str, Any]:
    """Convert MCP text content into a bounded observation or stable error."""
    stripped = raw_text.strip()
    if not stripped:
        return {"error": "empty_result"}
    # Wolfram Cloud may report argument/tool failures as ordinary TextContent.
    if stripped.startswith("[Error]"):
        return {"error": "tool_call_error"}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        if len(raw_text) > 4000:
            return {"error": "result_too_large"}
        return {"text": raw_text}
    if isinstance(parsed, dict):
        parsed.pop("instructions", None)
        parsed.pop("prompt", None)
        return parsed
    return {"value": parsed}


def science_observation_verification_outcome(
    observation: dict[str, Any] | None,
) -> str:
    """Classify a bounded Wolfram observation without exposing its contents."""
    if not isinstance(observation, dict):
        return "missing"
    if observation.get("verified") is True or observation.get("equivalent") is True:
        return "verified"
    if str(observation.get("result", "")).strip().casefold() == "true":
        return "verified"
    raw_text = observation.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return "unrecognized"
    try:
        root = ElementTree.fromstring(raw_text.strip())
    except ElementTree.ParseError:
        return "invalid_envelope"
    if root.tag != "result":
        return "invalid_envelope"
    lines = [line.strip() for line in "".join(root.itertext()).splitlines()]
    for index, line in enumerate(lines):
        if line.casefold() != "# result":
            continue
        values: list[str] = []
        for candidate in lines[index + 1:]:
            if candidate.startswith("#"):
                break
            if candidate:
                values.append(candidate)
        if len(values) != 1:
            return "ambiguous_result"
        return "verified" if values[0].casefold() == "true" else "not_verified"
    return "result_missing"


def science_observation_is_verified(observation: dict[str, Any] | None) -> bool:
    """Interpret only explicit true results from the bounded Wolfram contract.

    The hosted MCP currently returns a ``<result>`` text envelope rather than a
    JSON ``result`` field. Parse that envelope structurally and require the
    dedicated ``# Result`` section to be exactly ``True``; never accept a
    substring from the echoed query or explanatory text.
    """
    return science_observation_verification_outcome(observation) == "verified"


class ScienceToolResult:
    """Bounded, untrusted science observation — never course evidence."""

    def __init__(
        self,
        *,
        success: bool,
        observation: dict[str, Any] | None = None,
        error_code: str | None = None,
        latency_ms: int = 0,
    ):
        self.success = success
        self.observation = observation
        self.error_code = error_code
        self.latency_ms = latency_ms

    def to_safe_dict(self) -> dict[str, Any]:
        """Return a safe dict for persistence — never raw remote text."""
        if self.success and self.observation is not None:
            # Bound the observation size
            obs_json = json.dumps(self.observation, ensure_ascii=False)
            if len(obs_json) > 4000:
                return {"error": "result_too_large"}
            # Strip any instruction-like keys from remote response
            safe = dict(self.observation)
            safe.pop("instructions", None)
            safe.pop("prompt", None)
            return safe
        return {"error": self.error_code or "capability_unavailable"}


def execute_science_verification(
    *,
    tool: str,
    arguments: dict[str, Any],
    settings: Settings,
    expected_schema_hash: str | None = None,
    timeout_seconds: float | None = None,
) -> ScienceToolResult:
    """Execute one science tool call via MCP and return a bounded observation.

    Per ADR 006 §2.7:
    - Verifies server/protocol/tool allowlist/schema before calling
    - Sends only minimal expression, never course text/Memory/prompt
    - Remote exception text never enters observation or logs
    - WolframLanguageEvaluator is always rejected
    - Schema drift is a hard failure

    Per correction 005 §4: the schema hash is COMPARED, never overwritten.

    Returns ScienceToolResult with either a bounded observation dict
    (success=True) or a stable error code (success=False).
    """
    if not settings.wolfram_mcp_enabled:
        return ScienceToolResult(success=False, error_code="capability_unavailable")

    # Reject WolframLanguageEvaluator unconditionally
    if tool not in WOLFRAM_TOOL_WHITELIST:
        return ScienceToolResult(success=False, error_code="tool_not_allowed")

    started_at = time.perf_counter()

    async def _call() -> dict[str, Any]:
        try:
            from mcp.client.streamable_http import streamable_http_client
            from mcp.types import CallToolResult, TextContent
            from shared.mcp_execution_contract import compute_canonical_hash
        except ImportError:
            return {"error": "capability_unavailable"}

        url = settings.wolfram_mcp_url.rstrip("/")
        if not url.endswith("/mcp"):
            url = url + "/mcp"
        timeout = timeout_seconds or settings.wolfram_mcp_call_timeout_seconds

        import httpx as _httpx
        headers = (
            {"Authorization": f"Bearer {settings.wolfram_mcp_api_key}"}
            if settings.wolfram_mcp_api_key
            else None
        )
        async with _httpx.AsyncClient(timeout=timeout, headers=headers) as _http_client:
            async with streamable_http_client(url, http_client=_http_client) as (read, write, _):
                from mcp.client.session import ClientSession
                async with ClientSession(read, write) as session:
                    # Initialize and verify protocol
                    init_result = await session.initialize()
                    if init_result.protocolVersion != "2025-03-26":
                        return {"error": "protocol_drift"}

                    # list_tools and verify allowlist + schema
                    tools_result = await session.list_tools()
                    available_tools = {t.name for t in tools_result.tools}

                    # Verify all whitelisted tools are present
                    missing_tools = WOLFRAM_TOOL_WHITELIST - available_tools
                    if missing_tools:
                        return {"error": "tool_not_found"}

                    # Verify the requested tool exists
                    if tool not in available_tools:
                        return {"error": "tool_not_found"}

                    # Schema hash verification if expected hash provided
                    if expected_schema_hash:
                        tool_hashes = {}
                        for tool_name in WOLFRAM_TOOL_WHITELIST:
                            target_tool = next(
                                (t for t in tools_result.tools if t.name == tool_name), None
                            )
                            if target_tool is None:
                                return {"error": "tool_not_found"}
                            if not target_tool.inputSchema:
                                return {"error": "schema_drift"}
                            inp_hash = compute_canonical_hash(target_tool.inputSchema)
                            out_hash = compute_canonical_hash(target_tool.outputSchema or {})
                            tool_hashes[tool_name] = f"{inp_hash}:{out_hash}"

                        combined = json.dumps(
                            {"protocol": init_result.protocolVersion, "tools": tool_hashes},
                            sort_keys=True,
                        )
                        handshake_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]
                        if handshake_hash != expected_schema_hash:
                            return {"error": "schema_drift"}

                    # Call the tool
                    normalized_arguments = normalize_science_arguments(tool, arguments)
                    result: CallToolResult = await session.call_tool(
                        tool,
                        arguments=normalized_arguments,
                    )
                    if result.isError:
                        return {"error": "tool_call_error"}

                    raw_json = ""
                    for content in result.content:
                        if isinstance(content, TextContent):
                            raw_json += content.text
                    return parse_science_text_content(raw_json)

    try:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _call())
                observation = future.result()
        else:
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                observation = new_loop.run_until_complete(_call())
            finally:
                try:
                    new_loop.close()
                finally:
                    asyncio.set_event_loop(None)
    except Exception:
        observation = {"error": "mcp_connection_failed"}

    # Sanitize: only stable error codes
    if isinstance(observation, dict) and "error" in observation:
        error_code = observation["error"]
        if error_code not in STABLE_SCIENCE_ERRORS:
            observation = {"error": "mcp_connection_failed"}

    latency_ms = round((time.perf_counter() - started_at) * 1000)

    if isinstance(observation, dict) and "error" in observation:
        return ScienceToolResult(
            success=False,
            error_code=observation["error"],
            latency_ms=latency_ms,
        )

    return ScienceToolResult(
        success=True,
        observation=observation,
        latency_ms=latency_ms,
    )
