"""Tutor code-execution + Wolfram dual-MCP funnel (Section 9.2).

Each scenario drives the REAL ``tutor_generation.execute_tutor_turn`` on throwaway
Postgres (course scope), with the LLM provider, evidence search and the two tool
backends replaced by controlled fakes. Runs are labelled ``controlled_backend``
— never reported as real run_code / Wolfram Cloud passes (Spec 007 §9.2).

Asserts the persisted chain (TutorTurn, AgentRun, ProviderCall, AgentToolCall)
corresponds, that authorization gates zero-call behaviour, that tool failure
yields a stable limitation rather than a fabricated result, and that the Tutor
step / MCP budgets are not exceeded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import select

from learn_platform_api.db.models import CourseVersionSource
from learn_platform_api.services import code_lab_execution, tutor, tutor_generation

from quality_baseline import controlled, pgsupport, report


# ---------------------------------------------------------------------------
# Setup / driver
# ---------------------------------------------------------------------------


def _setup_turn(pg_db, monkeypatch, *, code_auth=False, science_auth=False, question="Explain the idea."):
    ws, course, cv, doc, ver, chunk = pgsupport.seed_tutor_course(pg_db)
    settings = pgsupport._make_settings(
        mcp_execution_adapter_url="http://controlled.invalid/mcp" if code_auth else None,
        wolfram_mcp_enabled=science_auth)
    pgsupport.patch_capability_projection(monkeypatch, code_ok=code_auth, science_ok=science_auth)
    monkeypatch.setattr(tutor, "enqueue_tutor_turn", lambda *_a: None)
    session = tutor.create_session(pg_db, settings, ws.id, course.id, cv.id)
    turn = tutor.create_turn(pg_db, settings, ws.id, session.id,
                             pgsupport.tutor_turn_payload(question=question,
                                                          code_tool_authorized=code_auth,
                                                          science_tool_authorized=science_auth),
                             f"t-{session.id[:6]}")
    turn.status = "running"; turn.worker_id = "test-worker"
    turn.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    pg_db.commit()
    cvs = pg_db.scalar(select(CourseVersionSource).where(
        CourseVersionSource.course_version_id == cv.id))
    monkeypatch.setattr(tutor_generation, "_search", lambda *_a: (
        [{"citation_id": "e1", "text": chunk.content}], {"e1": (chunk, cvs)}))
    return settings, turn


def _run(pg_db, settings, turn):
    tutor_generation.execute_tutor_turn(pg_db, settings, turn, worker_id="test-worker", lease_lost=None)
    pg_db.commit()


def _provider(plan, answer):
    return controlled.ScriptedProvider([(plan, controlled.usage()), (answer, controlled.usage())])


def _answer(text="Answer based on the material.", *, limitation=False):
    blocks = [{"block_key": "a", "type": "direct_answer", "text": text, "citation_ids": ["e1"]}]
    if limitation:
        blocks.append({"block_key": "lim", "type": "limitation",
                       "text": "The external computation tool could not verify this, so it is unverified.", "citation_ids": []})
    return {"blocks": blocks}


def _mcp_tools(pg_db, run_id, prefix):
    return [t for t in pgsupport.q_tool_calls(pg_db, agent_run_id=run_id) if prefix in t["tool_name"]]


# ---------------------------------------------------------------------------
# 1-2. Required + authorized -> actual tool call (code / science)
# ---------------------------------------------------------------------------


def test_tutor_code_required_authorized_runs_code(pg_db, monkeypatch):
    settings, turn = _setup_turn(pg_db, monkeypatch, code_auth=True, question="What does this print?")
    plan = {"intent": "concept_explanation", "queries": ["snippet"], "learning_context_use": "required",
            "teaching_moves": ["explain"],
            "code_requests": [{"language": "python", "source_code": "print(2 + 2)", "stdin": ""}]}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer("The snippet prints 4.")))
    monkeypatch.setattr(code_lab_execution, "execute_code_run_sync", controlled.controlled_execute_code_run_sync)
    _run(pg_db, settings, turn)

    td = pgsupport.q_tutor_turn(pg_db, turn.id)
    assert td["status"] == "succeeded"
    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    code_tools = _mcp_tools(pg_db, run["id"], "McpCodeTool")
    assert len(code_tools) == 1 and code_tools[0]["status"] == "succeeded"
    assert any(a["capability_id"] == "code_execution" and a["used_calls"] == 1
               for a in pgsupport.q_tutor_authorizations(pg_db, turn.id))


def test_tutor_science_required_authorized_calls_wolfram(pg_db, monkeypatch):
    settings, turn = _setup_turn(pg_db, monkeypatch, science_auth=True, question="Compute the symbolic result.")
    plan = {"intent": "concept_explanation", "queries": ["expression"], "learning_context_use": "required",
            "teaching_moves": ["explain"],
            "science_requests": [{"tool": "WolframAlpha", "arguments": {"query": "Integrate[x^2,x]"}}]}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer("The closed form is x^3/3.")))
    monkeypatch.setattr(tutor_generation, "_execute_science_tool_call",
                        controlled.controlled_tutor_science_backend("ok"))
    _run(pg_db, settings, turn)

    td = pgsupport.q_tutor_turn(pg_db, turn.id)
    assert td["status"] == "succeeded"
    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    sci_tools = _mcp_tools(pg_db, run["id"], "McpScienceTool")
    assert len(sci_tools) == 1 and sci_tools[0]["status"] == "succeeded"
    assert any(a["capability_id"] == "science_computation" and a["used_calls"] == 1
               for a in pgsupport.q_tutor_authorizations(pg_db, turn.id))
    # Tool call counts as part of the persisted chain with plan+answer ProviderCalls.
    assert [c["phase"] for c in pgsupport.q_provider_calls(pg_db, agent_run_id=run["id"])] == ["plan", "answer"]


# ---------------------------------------------------------------------------
# 3. Required sample but the model did NOT request the tool -> request missed
# ---------------------------------------------------------------------------


def test_tutor_code_required_but_not_requested(pg_db, monkeypatch):
    """A code-required question where the plan emits NO code_requests. Even though
    code is authorized, zero McpCodeTool calls occur — classified tool_request_missed."""
    settings, turn = _setup_turn(pg_db, monkeypatch, code_auth=True, question="What does this print?")
    plan = {"intent": "concept_explanation", "queries": ["snippet"], "learning_context_use": "required",
            "teaching_moves": ["explain"], "code_requests": []}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer()))
    _run(pg_db, settings, turn)
    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    assert _mcp_tools(pg_db, run["id"], "McpCodeTool") == []
    assert report.classify_science_tool_run({
        "expectation": "required", "requested": False, "authorized": True}) == "tool_request_missed"


# ---------------------------------------------------------------------------
# 4. Authorized negative control -> zero call (tool adds no value)
# ---------------------------------------------------------------------------


def test_tutor_science_authorized_negative_control_zero_call(pg_db, monkeypatch):
    """A conceptual question with science AUTHORIZED but where the plan (correctly)
    emits no science_requests — zero Wolfram calls despite authorization."""
    settings, turn = _setup_turn(pg_db, monkeypatch, science_auth=True, question="Define the term.")
    plan = {"intent": "concept_explanation", "queries": ["definition"], "learning_context_use": "required",
            "teaching_moves": ["explain"], "science_requests": []}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer()))
    _run(pg_db, settings, turn)
    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    assert _mcp_tools(pg_db, run["id"], "McpScienceTool") == []
    # Authorization existed but was not consumed.
    assert all(a["used_calls"] == 0 for a in pgsupport.q_tutor_authorizations(pg_db, turn.id))


# ---------------------------------------------------------------------------
# 5. Unauthorized -> zero call even if the plan requests the tool
# ---------------------------------------------------------------------------


def test_tutor_science_unauthorized_blocks_call(pg_db, monkeypatch):
    """No science authorization -> the plan's science_requests are force-cleared
    before execution, so zero McpScienceTool calls (Spec 004 §8.1, ADR 006 §2.4)."""
    settings, turn = _setup_turn(pg_db, monkeypatch, science_auth=False, question="Compute the symbolic result.")
    plan = {"intent": "concept_explanation", "queries": ["expression"], "learning_context_use": "required",
            "teaching_moves": ["explain"],
            "science_requests": [{"tool": "WolframAlpha", "arguments": {"query": "Integrate[x^2,x]"}}]}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer()))
    # If the (force-cleared) orchestration still reached the backend, this would
    # record a call; it must not.
    monkeypatch.setattr(tutor_generation, "_execute_science_tool_call",
                        controlled.controlled_tutor_science_backend("ok"))
    _run(pg_db, settings, turn)
    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    assert _mcp_tools(pg_db, run["id"], "McpScienceTool") == []
    assert pgsupport.q_tutor_authorizations(pg_db, turn.id) == []  # no auth row at all


# ---------------------------------------------------------------------------
# 6. Tool failure -> stable limitation, not a fabricated result
# ---------------------------------------------------------------------------


def test_tutor_science_failure_yields_limitation(pg_db, monkeypatch):
    settings, turn = _setup_turn(pg_db, monkeypatch, science_auth=True, question="Compute the symbolic result.")
    plan = {"intent": "concept_explanation", "queries": ["expression"], "learning_context_use": "required",
            "teaching_moves": ["explain"],
            "science_requests": [{"tool": "WolframAlpha", "arguments": {"query": "Integrate[x^2,x]"}}]}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer(limitation=True)))
    monkeypatch.setattr(tutor_generation, "_execute_science_tool_call",
                        controlled.controlled_tutor_science_backend("mcp_connection_failed"))
    _run(pg_db, settings, turn)
    td = pgsupport.q_tutor_turn(pg_db, turn.id)
    assert td["status"] == "succeeded"
    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    sci_tools = _mcp_tools(pg_db, run["id"], "McpScienceTool")
    assert len(sci_tools) == 1 and sci_tools[0]["status"] == "failed"
    # The answer must carry a limitation block — it must NOT claim the tool verified.
    blocks = td["answer_blocks"] or []
    assert any(b.get("type") == "limitation" for b in blocks), blocks


# ---------------------------------------------------------------------------
# 7. Budgets not exceeded + persisted chain corresponds
# ---------------------------------------------------------------------------


def test_tutor_budgets_and_persisted_chain_correspond(pg_db, monkeypatch):
    """The Tutor decision-step budget (<=8) and MCP budget (<=3) hold, and the
    Turn / AgentRun / ProviderCall / AgentToolCall chain corresponds (Spec 007 §8)."""
    settings, turn = _setup_turn(pg_db, monkeypatch, science_auth=True, code_auth=True,
                                 question="Compute and demonstrate.")
    plan = {"intent": "concept_explanation", "queries": ["expression"], "learning_context_use": "required",
            "teaching_moves": ["explain"],
            "science_requests": [{"tool": "WolframAlpha", "arguments": {"query": "1+1"}}],
            "code_requests": [{"language": "python", "source_code": "print(1+1)", "stdin": ""}]}
    monkeypatch.setattr(tutor_generation, "call_provider", _provider(plan, _answer("Result is 2.")))
    monkeypatch.setattr(tutor_generation, "_execute_science_tool_call",
                        controlled.controlled_tutor_science_backend("ok"))
    monkeypatch.setattr(code_lab_execution, "execute_code_run_sync", controlled.controlled_execute_code_run_sync)
    _run(pg_db, settings, turn)

    run = pgsupport.q_run(pg_db, tutor_turn_id=turn.id, role="tutor")
    assert run["status"] == "succeeded"
    assert run["step_count"] <= 8
    tools = pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"])
    mcp_tools = [t for t in tools if "McpCodeTool" in t["tool_name"] or "McpScienceTool" in t["tool_name"]]
    assert len(mcp_tools) <= 3
    # ProviderCalls exist and are owned by this run.
    calls = pgsupport.q_provider_calls(pg_db, agent_run_id=run["id"])
    assert len(calls) == 2 and {c["phase"] for c in calls} == {"plan", "answer"}
    # Both tool kinds fired.
    assert any("McpScienceTool" in t["tool_name"] for t in tools)
    assert any("McpCodeTool" in t["tool_name"] for t in tools)
