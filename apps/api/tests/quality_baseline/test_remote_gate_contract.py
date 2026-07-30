from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).parents[4] / "scripts" / "remote-gate.py"
SPEC = importlib.util.spec_from_file_location("stage5_remote_gate", SCRIPT)
assert SPEC and SPEC.loader
remote_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = remote_gate
SPEC.loader.exec_module(remote_gate)


def test_safe_report_accepts_only_the_remote_whitelist():
    record = {key: None for key in remote_gate.ALLOWED_RECORD_KEYS}
    record.update(
        {
            "sample_id": "safe-sample",
            "capability": "practice_coding",
            "repetition": 1,
            "final_status": "succeeded",
            "failure_category": "none",
            "layer": "real_remote",
            "controlled_backend": False,
            "remote_not_run": False,
        }
    )
    remote_gate.assert_safe_report({"records": [record]})


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "prompt",
        "question",
        "answer",
        "source_code",
        "stdout",
        "api_key",
        "url",
        "workspace_id",
        "run_id",
    ],
)
def test_safe_report_rejects_sensitive_or_identifying_keys(unsafe_key):
    with pytest.raises(RuntimeError, match="unsafe_report"):
        remote_gate.assert_safe_report(
            {"records": [{"sample_id": "sample", unsafe_key: "secret"}]}
        )


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "https://internal.example.invalid",
        "http://127.0.0.1:8000",
        r"C:\Users\Example\file.txt",
    ],
)
def test_safe_report_rejects_locations_in_values(unsafe_value):
    with pytest.raises(RuntimeError, match="unsafe_report_location"):
        remote_gate.assert_safe_report(
            {"records": [{"sample_id": "sample", "failure_category": unsafe_value}]}
        )


def test_lesson_ref_requires_four_nonblank_ids():
    ref = remote_gate.LessonRef.parse("course:version:lesson:lesson-version")
    assert ref.lesson_version_id == "lesson-version"
    with pytest.raises(Exception):
        remote_gate.LessonRef.parse("course:version:lesson")


def test_business_failure_precedes_missing_required_tool():
    assert remote_gate.RemoteGate._classify(
        status="failed",
        error="practice_artifact_schema_invalid",
        expectation="required",
        called=False,
        succeeded=False,
    ) == ("failed", "practice_artifact_schema_invalid")


def test_successful_required_sample_without_call_is_missed():
    assert remote_gate.RemoteGate._classify(
        status="succeeded",
        error=None,
        expectation="required",
        called=False,
        succeeded=False,
    ) == ("failed", "tool_call_missed")


def test_delivery_retry_wait_is_not_a_terminal_business_result():
    assert "retry_wait" not in remote_gate.TERMINAL


def test_duplicate_run_detection_distinguishes_retries_from_same_attempt():
    assert remote_gate.RemoteGate._has_duplicate_attempts([
        {"role": "tutor", "attempt_number": 1},
        {"role": "tutor", "attempt_number": 2},
    ]) is False
    assert remote_gate.RemoteGate._has_duplicate_attempts([
        {"role": "exercise_author", "attempt_number": 1},
        {"role": "exercise_author", "attempt_number": 1},
    ]) is True


def test_real_code_probe_fails_before_provider_matrix_when_cpp_is_unavailable():
    gate = remote_gate.RemoteGate.__new__(remote_gate.RemoteGate)
    gate.args = type("Args", (), {"workspace_id": "workspace", "code_timeout": 5})()
    gate._request = lambda *_args, **_kwargs: type(
        "Response", (), {"json": lambda self: {"id": "run"}}
    )()
    gate._poll = lambda *_args, **_kwargs: {
        "status": "failed",
        "exit_code": None,
    }

    with pytest.raises(RuntimeError, match="code_execution_probe_failed"):
        gate._probe_code_execution()
