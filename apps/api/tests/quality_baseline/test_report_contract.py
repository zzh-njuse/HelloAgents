"""Report-contract tests (packet §6): whitelist, forbidden-field defense, and the
eleven science-tool categories. Pure data — no Postgres."""

from __future__ import annotations

import pytest

from quality_baseline.report import (
    ALLOWED_SNAPSHOT_KEYS, FORBIDDEN_FIELD_NAMES, LAYER_CONTROLLED, LAYER_REAL_REMOTE,
    RunRecord, SCIENCE_CATEGORIES, assert_snapshot_safe, classify_science_tool_run, serialize,
)


def _record(**kw):
    base = dict(sample_id="x", capability="practice_science", language=None,
                request_mode="require_science", requested_item_count=1, repeat_ordinal=0)
    base.update(kw)
    return RunRecord(**base)


def test_serialize_emits_only_allowlisted_keys():
    snap = serialize(_record())
    assert set(snap.keys()) <= ALLOWED_SNAPSHOT_KEYS


def test_controlled_backend_is_the_default_layer():
    r = _record()
    assert r.layer == LAYER_CONTROLLED
    assert r.controlled_backend is True


def test_real_remote_layer_must_be_explicit_and_marked():
    r = _record(layer=LAYER_REAL_REMOTE, controlled_backend=False)
    snap = serialize(r)
    assert snap["layer"] == LAYER_REAL_REMOTE
    assert snap["controlled_backend"] is False


@pytest.mark.parametrize("bad_field", sorted(FORBIDDEN_FIELD_NAMES))
def test_snapshot_rejects_every_forbidden_field_name(bad_field):
    poisoned = serialize(_record())
    poisoned[bad_field] = "anything"
    with pytest.raises(ValueError, match="forbidden field name"):
        assert_snapshot_safe(poisoned)


@pytest.mark.parametrize("needle", [
    "Authorization", "Bearer sk-secret", "api_key=abc",
    "https://example.com", "http://10.0.0.1",
    "C:\\Users\\secret", "/home/oops", "/tmp/leak", ".env",
    "run_code", "WolframLanguageEvaluator",
])
def test_snapshot_rejects_forbidden_value_substrings(needle):
    poisoned = serialize(_record())
    poisoned["failure_category"] = needle
    with pytest.raises(ValueError, match="forbidden substring"):
        assert_snapshot_safe(poisoned)


def test_allowed_and_forbidden_key_sets_are_disjoint():
    assert ALLOWED_SNAPSHOT_KEYS.isdisjoint(FORBIDDEN_FIELD_NAMES)


def test_allowed_snapshot_keys_in_sync_with_runrecord():
    """The allowlist is a hand-maintained literal (packet Fix 2). It must stay
    COMPLETE for the CURRENT ``RunRecord`` fields, but it is NOT derived from
    them: if a field is added to ``RunRecord`` without a conscious update here,
    this assertion fails rather than auto-whitelisting the new field."""
    from dataclasses import asdict
    current_fields = frozenset(asdict(RunRecord("", "", None, "", 0, 0)).keys())
    assert ALLOWED_SNAPSHOT_KEYS == current_fields


def test_future_sensitive_field_is_not_auto_whitelisted():
    """Adding a field to ``RunRecord`` must NOT auto-enter the snapshot. A
    subclass carrying a hypothetical future sensitive field is still serialized
    WITHOUT that field, because the explicit allowlist does not name it."""
    from dataclasses import dataclass

    @dataclass
    class RunRecordWithFutureField(RunRecord):
        # A benign-named future field: it is neither in the allowlist NOR in the
        # forbidden-name set, so the only thing that can drop it is the allowlist.
        internal_debug_blob: str | None = None

    record = RunRecordWithFutureField(
        sample_id="x", capability="practice_science", language=None,
        request_mode="require_science", requested_item_count=1, repeat_ordinal=0)
    record.internal_debug_blob = "SHOULD NOT LEAK"

    assert "internal_debug_blob" not in ALLOWED_SNAPSHOT_KEYS
    snapshot = serialize(record)
    assert "internal_debug_blob" not in snapshot
    assert "SHOULD NOT LEAK" not in str(snapshot)


# --- Science-tool classifier: every category is reachable from structured facts --

CATEGORY_FACTS = {
    "tool_not_needed":                       {"expectation": "forbidden", "called": False},
    "succeeded_without_wolfram":             {"expectation": "optional", "called": False, "artifact_published": True},
    "tool_request_missed":                   {"expectation": "required", "requested": False},
    "tool_call_missed":                      {"expectation": "required", "requested": True, "authorized": True,
                                              "capability_ready": True, "called": False, "artifact_published": True},
    "forbidden_tool_called":                 {"expectation": "forbidden", "called": True,
                                              "requested": True, "authorized": True, "capability_ready": True,
                                              "result_valid": True, "reference_verified": True,
                                              "artifact_published": True},
    "authorization_missing":                 {"expectation": "required", "requested": True, "authorized": False},
    "capability_unavailable":                {"expectation": "required", "requested": True, "authorized": True,
                                              "capability_ready": False, "called": False},
    "schema_drift":                          {"expectation": "required", "requested": True, "authorized": True,
                                              "called": True, "error_code": "schema_drift"},
    "mcp_connection_failed":                 {"expectation": "required", "requested": True, "authorized": True,
                                              "called": True, "error_code": "mcp_connection_failed"},
    "tool_result_invalid":                   {"expectation": "required", "requested": True, "authorized": True,
                                              "called": True, "error_code": "tool_call_error"},
    "scientific_reference_unverified":       {"expectation": "required", "requested": True, "authorized": True,
                                              "called": True, "result_valid": True, "reference_verified": False},
    "artifact_failed_after_tool_success":    {"expectation": "required", "requested": True, "authorized": True,
                                              "called": True, "result_valid": True, "reference_verified": True,
                                              "artifact_published": False},
    "succeeded_with_wolfram":                {"expectation": "required", "requested": True, "authorized": True,
                                              "called": True, "result_valid": True, "reference_verified": True,
                                              "artifact_published": True},
}


@pytest.mark.parametrize("expected_category", SCIENCE_CATEGORIES)
def test_classifier_reaches_every_category(expected_category):
    facts = dict(CATEGORY_FACTS[expected_category])
    assert classify_science_tool_run(facts) == expected_category


def test_classifier_ignores_natural_language_and_exception_bodies():
    """Classification must come from structured facts, not from parsing text."""
    facts = {
        "expectation": "required", "requested": True, "authorized": True, "called": True,
        "error_code": "mcp_connection_failed",
        # Noise that must NOT influence the result:
        "exception_body": "ConnectionRefusedError: wolfram.example.com refused",
        "log_line": "Wolfram said: [Error] bad input",
        "answer_text": "I could not verify the result.",
    }
    assert classify_science_tool_run(facts) == "mcp_connection_failed"


# --- Science-tool classifier: full branch + priority table (packet Fix 1) -------
#
# Covers every required/optional/forbidden × called/uncalled combination and the
# priority invariants: a forbidden-but-called run is NEVER a success, and a
# required-but-uncalled run (requested+authorized+ready) is NEVER a success.
_CONTRACT_TABLE = [
    # (label, facts, expected)
    # forbidden
    ("forbidden/uncalled", {"expectation": "forbidden", "called": False}, "tool_not_needed"),
    ("forbidden/called even if it 'succeeded'",
     {"expectation": "forbidden", "called": True, "requested": True, "authorized": True,
      "capability_ready": True, "result_valid": True, "reference_verified": True,
      "artifact_published": True}, "forbidden_tool_called"),
    ("forbidden/called with no auth either",
     {"expectation": "forbidden", "called": True, "requested": False, "authorized": False},
     "forbidden_tool_called"),
    # optional
    ("optional/uncalled", {"expectation": "optional", "called": False, "artifact_published": True},
     "succeeded_without_wolfram"),
    # required
    ("required/not requested", {"expectation": "required", "requested": False}, "tool_request_missed"),
    ("required/requested+authorized+ready but NOT called",
     {"expectation": "required", "requested": True, "authorized": True, "capability_ready": True,
      "called": False, "artifact_published": True}, "tool_call_missed"),
    ("required/requested+authorized+ready NOT called, unpublished",
     {"expectation": "required", "requested": True, "authorized": True, "capability_ready": True,
      "called": False, "artifact_published": False}, "tool_call_missed"),
    ("required/called+succeeded",
     {"expectation": "required", "requested": True, "authorized": True, "called": True,
      "result_valid": True, "reference_verified": True, "artifact_published": True}, "succeeded_with_wolfram"),
]


@pytest.mark.parametrize(
    ("facts", "expected"),
    [(facts, expected) for (_label, facts, expected) in _CONTRACT_TABLE],
    ids=[label for (label, _facts, _expected) in _CONTRACT_TABLE],
)
def test_classifier_contract_table(facts, expected):
    assert classify_science_tool_run(dict(facts)) == expected


def test_forbidden_called_never_classified_as_success():
    """A forbidden tool that ran must not reach any success category, even when
    every downstream signal looks perfect (priority over success fields)."""
    success_like = {
        "expectation": "forbidden", "called": True, "requested": True, "authorized": True,
        "capability_ready": True, "result_valid": True, "reference_verified": True,
        "artifact_published": True,
    }
    result = classify_science_tool_run(success_like)
    assert result == "forbidden_tool_called"
    assert result not in {"succeeded_with_wolfram", "succeeded_without_wolfram", "tool_not_needed"}


def test_required_uncalled_never_classified_as_success():
    """A required tool that was requested+authorized+ready but never called must
    not be reported as succeeded_without_wolfram, even if the artifact published."""
    result = classify_science_tool_run({
        "expectation": "required", "requested": True, "authorized": True,
        "capability_ready": True, "called": False, "artifact_published": True,
    })
    assert result == "tool_call_missed"
    assert result not in {"succeeded_with_wolfram", "succeeded_without_wolfram"}


def test_classifier_priority_authorization_before_capability_before_call():
    """Existing priority order is preserved: authorization_missing -> capability
    _unavailable -> tool_call_missed, and each is independent of artifact state."""
    assert classify_science_tool_run(
        {"expectation": "required", "requested": True, "authorized": False, "called": False}
    ) == "authorization_missing"
    assert classify_science_tool_run(
        {"expectation": "required", "requested": True, "authorized": True,
         "capability_ready": False, "called": False}
    ) == "capability_unavailable"
