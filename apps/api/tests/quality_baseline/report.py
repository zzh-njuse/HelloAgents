"""Safe report contract for the Slice 2B Batch A quality baseline (packet §6).

Pure eval/report data structures — never enters the product API/ORM. A
``RunRecord`` captures one baseline run; the science-tool classifier maps a run
to one of the eleven stable categories accepted by Spec 007 §7 / packet §6,
derived ONLY from structured facts (never from exception bodies, logs or natural
language).

Serialization is whitelisted: ``serialize()`` emits only ``ALLOWED_SNAPSHOT_KEYS``
and ``assert_snapshot_safe()`` rejects forbidden fields. The forbidden set covers
prompt/messages, lesson/source/evidence text, stem/answer/rubric, source/reference/
student code, public/hidden tests + harness, raw provider/compiler/Wolfram I/O,
keys, Authorization, URLs and absolute paths (packet §6 / §13).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Layers + stable categories
# ---------------------------------------------------------------------------

LAYER_CONTROLLED = "controlled"
LAYER_REAL_REMOTE = "real_remote"

# Science-tool funnel categories (Spec 007 §7, packet §6). Derived from facts.
#
# The two contract-violation categories below (OCR fix packet Fix 1) are NOT
# success states: a forbidden tool that was called, or a required tool that was
# requested+authorized+ready but never actually called, must never be classified
# as a success (succeeded_with_wolfram / succeeded_without_wolfram).
SCIENCE_CATEGORIES = (
    "tool_not_needed",
    "tool_request_missed",
    "tool_call_missed",            # required: requested+authorized+ready, but never called
    "forbidden_tool_called",       # forbidden expectation, yet the tool was called
    "authorization_missing",
    "capability_unavailable",
    "schema_drift",
    "mcp_connection_failed",
    "tool_result_invalid",
    "scientific_reference_unverified",
    "artifact_failed_after_tool_success",
    "succeeded_with_wolfram",
    "succeeded_without_wolfram",
)

# Stable tool error codes that map to schema/connection/result classifications.
_SCHEMA_ERROR = "schema_drift"
_CONNECTION_ERROR = "mcp_connection_failed"
_RESULT_INVALID_ERRORS = frozenset({
    "tool_call_error", "tool_result_invalid", "invalid_tool_result",
    "result_too_large", "empty_result", "non_json_result",
    "tool_not_found", "tool_not_allowed", "protocol_drift",
})


def classify_science_tool_run(facts: dict[str, Any]) -> str:
    """Map a science-tool run's structured facts to one stable category.

    Pure decision over facts — never reads exception bodies, logs or NL answers.
    ``facts`` keys (all optional, defaulting to the safe value):
    expectation, requested, authorized, capability_ready, called, error_code,
    result_valid, reference_verified, artifact_published.
    """
    expectation = facts.get("expectation")
    requested = bool(facts.get("requested"))
    authorized = bool(facts.get("authorized"))
    capability_ready = facts.get("capability_ready", True)
    called = bool(facts.get("called"))
    error_code = facts.get("error_code")
    result_valid = bool(facts.get("result_valid"))
    reference_verified = bool(facts.get("reference_verified"))
    artifact_published = bool(facts.get("artifact_published"))

    # A forbidden tool that was called AT ALL is a contract violation, regardless
    # of whether it happened to succeed. This is checked before any success
    # classification so a forbidden-but-successful run can never be reported as
    # succeeded_with_wolfram / succeeded_without_wolfram (packet Fix 1).
    if expectation == "forbidden" and called:
        return "forbidden_tool_called"

    # Tool was genuinely not needed and was not called.
    if expectation in ("forbidden", "optional") and not called:
        return "tool_not_needed" if expectation == "forbidden" else "succeeded_without_wolfram"

    # A required sample whose plan never requested the tool.
    if expectation == "required" and not requested:
        return "tool_request_missed"

    # Requested but never authorized.
    if requested and not authorized:
        return "authorization_missing"

    # Authorized but the capability was not ready.
    if authorized and not capability_ready:
        return "capability_unavailable"

    # Tool was called — classify by where the failure sits. The relative order of
    # schema / connection / invalid-result / reference / artifact is unchanged.
    if called:
        if error_code == _SCHEMA_ERROR:
            return "schema_drift"
        if error_code == _CONNECTION_ERROR:
            return "mcp_connection_failed"
        if error_code in _RESULT_INVALID_ERRORS or not result_valid:
            return "tool_result_invalid"
        if not reference_verified:
            return "scientific_reference_unverified"
        if not artifact_published:
            return "artifact_failed_after_tool_success"
        return "succeeded_with_wolfram"

    # Required sample: the plan requested the tool, authorization existed and the
    # capability was ready, yet the tool was never actually called (an execution
    # gap). This is a stable failure category — it must NOT fall through to a
    # success classification (packet Fix 1).
    if expectation == "required":
        return "tool_call_missed"

    # Optional sample that was not called and not published (e.g. local failure).
    if not artifact_published:
        return "tool_not_needed"
    return "succeeded_without_wolfram"


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    """One baseline run. All fields are aggregation fields or stable categories."""
    # Identity
    sample_id: str
    capability: str
    language: str | None
    request_mode: str
    requested_item_count: int
    repeat_ordinal: int
    layer: str = LAYER_CONTROLLED          # controlled | real_remote
    controlled_backend: bool = True        # True: fake/local backend, NOT real Judge0/Wolfram
    # Item accounting
    final_item_count: int | None = None
    item_type_counts: dict[str, int] = field(default_factory=dict)
    specialized_item_count: int | None = None
    # Tool funnel
    tool_expectation: str | None = None
    tool_requested: bool = False
    tool_authorized: bool = False
    tool_called: bool = False
    tool_succeeded: bool = False
    # Stage statuses (stable strings only)
    artifact_status: str | None = None
    reference_status: str | None = None     # passed|compile_failed|test_mismatch|skipped|...
    compiler_status: str | None = None
    grading_status: str | None = None
    final_status: str | None = None         # set_published|job_succeeded|job_failed|...
    # Provider
    provider_phases: list[str] = field(default_factory=list)
    provider_status: str | None = None
    provider_input_tokens: int | None = None
    provider_output_tokens: int | None = None
    finish_reason: str | None = None
    # Counts
    repair_count: int = 0
    provider_call_count: int = 0
    mcp_call_count: int = 0
    step_count: int | None = None
    # Failure classification
    failure_phase: str | None = None
    failure_category: str | None = None     # a stable science category or a stable job error code
    science_tool_category: str | None = None
    # Cost / latency
    latency_ms: int | None = None
    token_total: int | None = None
    cny_cost: str | None = None             # decimal string, or None when unknown
    cny_unknown_reason: str | None = None


# ---------------------------------------------------------------------------
# Serialization whitelist + forbidden-field defense
# ---------------------------------------------------------------------------

# Hand-maintained, EXPLICIT allowlist of fields a snapshot may emit. This is a
# literal, immutable set — it is NOT derived from ``dataclasses.fields``,
# ``asdict`` or any instance's attributes (packet Fix 2). Adding a field to
# ``RunRecord`` therefore does NOT auto-whitelist it: the new field is dropped by
# ``serialize`` until it is consciously added here, and ``assert_snapshot_safe``
# remains a second line of defense. ``test_allowed_snapshot_keys_in_sync_with_runrecord``
# keeps this list complete for the CURRENT fields without making it auto-derived.
ALLOWED_SNAPSHOT_KEYS = frozenset({
    # Identity
    "sample_id", "capability", "language", "request_mode",
    "requested_item_count", "repeat_ordinal", "layer", "controlled_backend",
    # Item accounting
    "final_item_count", "item_type_counts", "specialized_item_count",
    # Tool funnel
    "tool_expectation", "tool_requested", "tool_authorized",
    "tool_called", "tool_succeeded",
    # Stage statuses
    "artifact_status", "reference_status", "compiler_status",
    "grading_status", "final_status",
    # Provider
    "provider_phases", "provider_status", "provider_input_tokens",
    "provider_output_tokens", "finish_reason",
    # Counts
    "repair_count", "provider_call_count", "mcp_call_count", "step_count",
    # Failure classification
    "failure_phase", "failure_category", "science_tool_category",
    # Cost / latency
    "latency_ms", "token_total", "cny_cost", "cny_unknown_reason",
})

# Field names (and value substrings) that must NEVER appear in a snapshot.
FORBIDDEN_FIELD_NAMES = frozenset({
    "prompt", "messages", "lesson", "source", "evidence", "stem", "answer",
    "rubric", "reference_solution", "source_code", "student_code", "code",
    "hidden_tests", "public_tests", "public_examples", "harness", "tests",
    "compiler_output", "wolfram_raw", "raw", "api_key", "authorization",
    "url", "base_url", "absolute_path", "secret", "token",  # 'token' as a field name
    "question", "observation", "stderr", "stdout",
})

# Substrings that, if found in any serialized value, indicate a leak.
_FORBIDDEN_VALUE_SUBSTRINGS = (
    "Authorization", "Bearer ", "api_key", "apikey",
    "http://", "https://",
    "C:\\", "/home/", "/Users/", "/tmp/", ".env",
    "run_code", "WolframLanguageEvaluator",
)


def serialize(record: RunRecord) -> dict[str, Any]:
    """Serialize a RunRecord to a whitelisted snapshot dict.

    Only ``ALLOWED_SNAPSHOT_KEYS`` are emitted. ``assert_snapshot_safe`` is then
    applied so a leak fails loudly rather than persisting.
    """
    snapshot = {k: v for k, v in asdict(record).items() if k in ALLOWED_SNAPSHOT_KEYS}
    assert_snapshot_safe(snapshot)
    return snapshot


def assert_snapshot_safe(snapshot: dict[str, Any]) -> None:
    """Reject any forbidden key or forbidden value substring in a snapshot.

    Raises ``ValueError`` naming the offending key/substring. Used both by
    ``serialize()`` and by the report-contract tests' forbidden-field defense.
    """
    leaked_keys = set(snapshot.keys()) & FORBIDDEN_FIELD_NAMES
    if leaked_keys:
        raise ValueError(f"snapshot leaked forbidden field name(s): {sorted(leaked_keys)}")
    for key, value in snapshot.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            text = repr(value)
        else:
            text = str(value)
        for needle in _FORBIDDEN_VALUE_SUBSTRINGS:
            if needle in text:
                raise ValueError(
                    f"snapshot field {key!r} contains forbidden substring {needle!r}"
                )


def cny_unknown(reason: str) -> tuple[None, str]:
    """Helper: build a (cost, unknown_reason) pair when CNY cost cannot be computed."""
    return None, reason
