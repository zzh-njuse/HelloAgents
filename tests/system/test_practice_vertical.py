"""Real API / Redis worker / Postgres / MCP-client vertical system tests for
Practice (Slice 2B Batch B packet §7/§8/§12).

Every path drives the public HTTP API, is consumed by the REAL out-of-process
practice-worker over Redis, validates coding references / science answers
through the REAL MCP clients (mcp-execution -> fake execution backend;
science_tool_service -> fake Wolfram), and is asserted from the API and from a
NEW Postgres Session plus the controlled fakes' atomic counters — never from
mock call counts alone (Spec 006 §4.2, packet §7).
"""

from __future__ import annotations

import httpx
import pytest

from controlled_helpers import (
    API_URL, create_practice_set, fake_exec_calls, fake_wolfram_calls,
    get_set, poll_attempt, poll_job, reset_fake_exec, reset_fake_wolfram,
    reset_stub, runs_for, seed_practice_lesson, submit_attempt, provider_calls,
    tool_calls, wait_for_environment,
)


@pytest.fixture(scope="module", autouse=True)
def env_ready():
    wait_for_environment(practice=True)


def _client():
    return httpx.Client(base_url=API_URL, timeout=15)


# Reference solutions that the real learner would submit (correct identity).
_CORRECT = {
    "java": "class Solution { static String solve(String input) { return input; } }",
    "cpp": "std::string solve(const std::string& input){ return input; }",
}


def test_java_generation_grading_and_run_record():
    fx = seed_practice_lesson(algorithmic=True, executable=True)
    reset_stub("practice_java_success"); reset_fake_exec("default"); reset_fake_wolfram("success")
    with _client() as c:
        job = create_practice_set(c, fx, item_count=1, mode="require_coding",
                                  language="java", code_auth=True)
        finished = poll_job(c, fx["workspace_id"], job["id"])

    assert finished["status"] == "succeeded", finished
    # Fix 8: the temporary httpx.Client must be closed (context manager), not
    # leaked as an unclosed connection.
    with _client() as c:
        practice_set = get_set(c, fx["workspace_id"], finished["practice_set_id"])
    assert practice_set["item_count"] == 1
    assert practice_set["lifecycle_status"] == "active"
    item = practice_set["items"][0]
    assert item["item_type"] == "coding"
    assert item["interaction_spec"]["language"] == "java"

    # Real DB facts (new Session): generation run + provider calls + tool calls.
    gen_runs = runs_for({"practice_job_id": finished["id"], "role": "exercise_author"})
    assert gen_runs and gen_runs[0]["status"] == "succeeded"
    gen_run = gen_runs[0]["id"]
    phases = [p["phase"] for p in provider_calls(gen_run)]
    assert phases == ["plan", "generation"]
    assert all(p["status"] == "succeeded" for p in provider_calls(gen_run))
    tc = tool_calls(gen_run)
    assert any(t["tool_name"] == "ValidateCodingReference" and t["status"] == "succeeded" for t in tc)
    assert not any(t["tool_name"].startswith("McpScienceTool") for t in tc)  # no Wolfram on a coding lesson
    # The reference really ran on the controlled execution backend.
    assert fake_exec_calls("default") >= 1

    # Submit a correct answer and grade it through the real worker + MCP.
    before = fake_exec_calls("default")
    with _client() as c:
        attempt = submit_attempt(c, fx["workspace_id"], item["id"], source_code=_CORRECT["java"])
        graded = poll_attempt(c, fx["workspace_id"], attempt["id"])
    assert graded["status"] == "succeeded", graded
    feedback = graded["feedback"]
    assert feedback["verdict"] == "correct"
    assert feedback["score"] == 100
    assert feedback["coding_tests_passed"] == feedback["coding_tests_total"]
    # Grading ran the learner code on the controlled execution backend too.
    assert fake_exec_calls("default") > before
    grade_runs = runs_for({"practice_job_id": graded["practice_job_id"], "role": "answer_grader"})
    assert grade_runs and grade_runs[0]["status"] == "succeeded"
    assert any(t["tool_name"] == "CodeExecution" and t["status"] == "succeeded"
               for t in tool_calls(grade_runs[0]["id"]))


def test_cpp_generation_uses_cpp_not_python():
    fx = seed_practice_lesson(algorithmic=True, executable=True)
    reset_stub("practice_cpp_success"); reset_fake_exec("default"); reset_fake_wolfram("success")
    with _client() as c:
        job = create_practice_set(c, fx, item_count=1, mode="require_coding",
                                  language="cpp", code_auth=True)
        finished = poll_job(c, fx["workspace_id"], job["id"])
    assert finished["status"] == "succeeded", finished
    with _client() as c:
        practice_set = get_set(c, fx["workspace_id"], finished["practice_set_id"])
    item = practice_set["items"][0]
    assert item["item_type"] == "coding"
    assert item["interaction_spec"]["language"] == "cpp"  # C++, not Python substitute
    gen_run = runs_for({"practice_job_id": finished["id"], "role": "exercise_author"})[0]["id"]
    assert any(t["tool_name"] == "ValidateCodingReference" and t["status"] == "succeeded"
               for t in tool_calls(gen_run))


def test_science_wolfram_required_calls_tool_and_publishes():
    fx = seed_practice_lesson(math=True, computable=True)
    reset_stub("practice_science_wolfram_required"); reset_fake_exec("default"); reset_fake_wolfram("success")
    assert fake_wolfram_calls("success") == 0
    with _client() as c:
        job = create_practice_set(c, fx, item_count=1, mode="require_science", science_auth=True)
        finished = poll_job(c, fx["workspace_id"], job["id"])
    assert finished["status"] == "succeeded", finished
    with _client() as c:
        practice_set = get_set(c, fx["workspace_id"], finished["practice_set_id"])
    assert practice_set["items"][0]["item_type"] == "scientific"
    gen_run = runs_for({"practice_job_id": finished["id"], "role": "exercise_author"})[0]["id"]
    tc = tool_calls(gen_run)
    # Practice verifies science via VerifyScientificAnswer (not the Tutor Mcp* tools).
    assert any(t["tool_name"] == "VerifyScientificAnswer" and t["status"] == "succeeded" for t in tc)
    assert not any(t["tool_name"].startswith("McpScienceTool") or t["tool_name"].startswith("McpCodeTool") for t in tc)
    # The required science sample really called the allowlisted Wolfram Tool.
    assert fake_wolfram_calls("success") >= 1


def test_science_negative_zero_wolfram_even_when_authorized():
    fx = seed_practice_lesson(math=True, computable=True)
    reset_stub("practice_science_negative"); reset_fake_exec("default"); reset_fake_wolfram("success")
    with _client() as c:
        # ``auto`` may publish a locally verifiable scientific item without a
        # remote call. ``require_science`` now guarantees Wolfram-backed
        # reference verification and is covered by the preceding positive.
        job = create_practice_set(c, fx, item_count=1, mode="auto", science_auth=True)
        finished = poll_job(c, fx["workspace_id"], job["id"])
    assert finished["status"] == "succeeded", finished
    gen_run = runs_for({"practice_job_id": finished["id"], "role": "exercise_author"})[0]["id"]
    assert not any(t["tool_name"] == "VerifyScientificAnswer" for t in tool_calls(gen_run))
    # Authorized but the tool was not needed: zero Wolfram calls (counter proof).
    assert fake_wolfram_calls("success") == 0


def test_counterfactual_language_mismatch_fails_no_set():
    """A java item returned for a cpp-only request must be rejected (§12)."""
    fx = seed_practice_lesson(algorithmic=True, executable=True)
    reset_stub("practice_java_success"); reset_fake_exec("default"); reset_fake_wolfram("success")
    with _client() as c:
        job = create_practice_set(c, fx, item_count=1, mode="require_coding",
                                  language="cpp", code_auth=True)
        finished = poll_job(c, fx["workspace_id"], job["id"])
    assert finished["status"] == "failed", finished
    assert finished["practice_set_id"] is None


def test_counterfactual_cpp_compile_failure_publishes_no_set():
    """A C++ reference that genuinely fails to compile must not publish a Set (§12)."""
    fx = seed_practice_lesson(algorithmic=True, executable=True)
    reset_stub("practice_cpp_compile_fail"); reset_fake_exec("default"); reset_fake_wolfram("success")
    with _client() as c:
        job = create_practice_set(c, fx, item_count=1, mode="require_coding",
                                  language="cpp", code_auth=True)
        finished = poll_job(c, fx["workspace_id"], job["id"])
    assert finished["status"] == "failed", finished
    assert finished["practice_set_id"] is None


def test_counter_isolation_between_scenarios():
    """Reset isolates counters; cross-scenario pollution must not occur (§12)."""
    reset_fake_wolfram("success")
    assert fake_wolfram_calls("success") == 0
    reset_fake_wolfram("invalid_result")
    # The 'success' counter is unaffected by switching to another scenario.
    assert fake_wolfram_calls("success") == 0
