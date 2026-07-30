"""Real API / Redis worker / Postgres / MCP-client vertical system tests for
Tutor code + Wolfram tools (Slice 2B Batch B packet §8.3/§12).

Each turn is created via the public HTTP API and run by the REAL tutor-system
worker. Code runs through the REAL execution MCP client (-> fake execution
backend); science runs through the REAL science MCP client (-> fake Wolfram).
Evidence is read from the API (turn tool-call counts) and a NEW Postgres Session
(AgentRun / ProviderCall / AgentToolCall) plus the controlled fakes' atomic
counters.
"""

from __future__ import annotations

import httpx
import pytest

from controlled_helpers import (
    API_URL, create_tutor_turn, fake_exec_calls, fake_wolfram_calls,
    poll_turn, provider_calls, reset_fake_exec, reset_fake_wolfram, reset_stub,
    runs_for, seed_tutor_course, tool_calls, wait_for_environment,
)


@pytest.fixture(scope="module", autouse=True)
def env_ready():
    wait_for_environment(tutor=True)


def _client():
    return httpx.Client(base_url=API_URL, timeout=15)


def _run_for_turn(turn_id: str) -> str:
    runs = runs_for({"tutor_turn_id": turn_id, "role": "tutor"})
    assert runs, "no tutor AgentRun for turn"
    assert runs[0]["status"] == "succeeded", runs[0]
    return runs[0]["id"]


def test_tutor_code_required_calls_execution_tool():
    fx = seed_tutor_course()
    reset_stub("tutor_code_required"); reset_fake_exec("default"); reset_fake_wolfram("success")
    before = fake_exec_calls("default")
    with _client() as c:
        turn = create_tutor_turn(c, fx, question="Run a small program and tell me the output.",
                                 code_auth=True)
        result = poll_turn(c, fx["workspace_id"], turn["id"])
    assert result["status"] == "succeeded", result
    assert result["code_tool_used"] is True
    assert result["code_tool_call_count"] >= 1
    run = _run_for_turn(turn["id"])
    assert any(t["tool_name"].startswith("McpCodeTool") and t["status"] == "succeeded"
               for t in tool_calls(run))
    assert fake_exec_calls("default") > before


def test_tutor_code_negative_zero_calls_when_authorized():
    fx = seed_tutor_course()
    reset_stub("tutor_code_negative"); reset_fake_exec("default"); reset_fake_wolfram("success")
    before = fake_exec_calls("default")
    with _client() as c:
        turn = create_tutor_turn(c, fx, question="Explain the concept in plain terms.",
                                 code_auth=True)
        result = poll_turn(c, fx["workspace_id"], turn["id"])
    assert result["status"] == "succeeded", result
    # Authorized, but the model did not request code -> zero execution calls.
    assert result["code_tool_call_count"] == 0
    run = _run_for_turn(turn["id"])
    assert not any(t["tool_name"].startswith("McpCodeTool") for t in tool_calls(run))
    assert fake_exec_calls("default") == before


def test_tutor_wolfram_required_calls_allowlisted_tool():
    fx = seed_tutor_course()
    reset_stub("tutor_wolfram_required"); reset_fake_exec("default"); reset_fake_wolfram("success")
    assert fake_wolfram_calls("success") == 0
    with _client() as c:
        turn = create_tutor_turn(c, fx, question="Compute the symbolic result and verify it.",
                                 science_auth=True)
        result = poll_turn(c, fx["workspace_id"], turn["id"])
    assert result["status"] == "succeeded", result
    assert result["science_tool_used"] is True
    assert result["science_tool_call_count"] >= 1
    run = _run_for_turn(turn["id"])
    tc = tool_calls(run)
    # Allowlisted Tool only; forbidden tool never appears.
    assert any(t["tool_name"] == "McpScienceTool:WolframAlpha" and t["status"] == "succeeded" for t in tc)
    assert not any("WolframLanguageEvaluator" in t["tool_name"] for t in tc)
    assert fake_wolfram_calls("success") >= 1
    # Provider chain is real: plan + answer.
    assert [p["phase"] for p in provider_calls(run)] == ["plan", "answer"]


def test_tutor_wolfram_negative_zero_calls_when_authorized():
    fx = seed_tutor_course()
    reset_stub("tutor_wolfram_negative"); reset_fake_exec("default"); reset_fake_wolfram("success")
    # Fix 8: assert the baseline Wolfram counter is 0 BEFORE the Turn, so the
    # post-turn "still 0" assertion observes this run's calls only.
    assert fake_wolfram_calls("success") == 0
    with _client() as c:
        turn = create_tutor_turn(c, fx, question="Define the term in your own words.",
                                 science_auth=True)
        result = poll_turn(c, fx["workspace_id"], turn["id"])
    assert result["status"] == "succeeded", result
    assert result["science_tool_call_count"] == 0
    run = _run_for_turn(turn["id"])
    assert not any(t["tool_name"].startswith("McpScienceTool") for t in tool_calls(run))
    # Authorized but not needed: zero Wolfram calls (counter proof).
    assert fake_wolfram_calls("success") == 0
