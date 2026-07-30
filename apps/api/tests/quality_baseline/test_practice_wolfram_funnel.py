"""Practice scientific-item Wolfram call funnel (Section 9.1).

Each scenario drives the REAL ``practice_generation.execute_generation`` (and, for
grading, ``execute_grading``) on throwaway Postgres, with the LLM provider,
retrieval and the Wolfram science-tool seam replaced. The science verifier is a
spying controlled backend: it never contacts Wolfram Cloud, and the run is
labelled ``controlled_backend`` — never reported as a real Wolfram pass
(Spec 007 §9.1, packet §9.1).

The stable science-tool category is derived from STRUCTURED facts only (the
scripted ``needs_remote`` flag, the captured ``ScienceToolResult``, and the
persisted Set/Job outcome queried from a NEW session) via
``classify_science_tool_run`` — never from exception bodies or natural language.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learn_platform_api.db.models import JobToolAuthorization, PracticeItem
from learn_platform_api.services import practice, practice_generation
from sqlalchemy import select

from quality_baseline import controlled, pgsupport, report, samples


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _science_lesson(pg_db, monkeypatch, *, science_auth=True, capability_ready=True, mode="require_science"):
    settings, job, chunk, doc, ver = pgsupport.prepare_budget_job(
        pg_db, monkeypatch, mode=mode, item_count=1,
        science_auth=science_auth, science_enabled=capability_ready or science_auth,
        math=True, computable=True)
    return settings, job, chunk, doc, ver


def _spying_verifier(policy, error_code="mcp_connection_failed"):
    """Wrap a controlled verifier with a spy that records the last ScienceToolResult."""
    captured: dict = {}
    base = controlled.make_science_verifier(policy, error_code=error_code)

    def _spy(*a, **k):
        res = base(*a, **k)
        captured["result"] = res
        return res
    return _spy, captured


def _run_generation(pg_db, settings, job, worker_id="test-worker"):
    """Run execute_generation worker-style: commit on success; on ValueError,
    finalize the Job as failed with the stable code (as the real worker does)."""
    from learn_platform_api.db.models import PracticeJob

    try:
        practice_generation.execute_generation(pg_db, settings, job, worker_id=worker_id)
        pg_db.commit()
        return None
    except ValueError as exc:
        code = str(exc.value) if hasattr(exc, "value") else str(exc)
        pg_db.rollback()
        refreshed = pg_db.get(PracticeJob, job.id)
        refreshed.status = "failed"
        refreshed.error_code = code
        refreshed.worker_id = None
        refreshed.lease_expires_at = None
        refreshed.completed_at = datetime.now(timezone.utc)
        pg_db.commit()
        return code


def _science_facts(pg_db, job, *, expectation, needs_remote, captured, authorized, capability_ready):
    """Build structured facts for the classifier from persisted state + the spy."""
    ps = pgsupport.q_set(pg_db, job.id)
    artifact_published = ps is not None and ps["lifecycle_status"] == "active"
    result = captured.get("result")
    called = result is not None
    error_code = result.error_code if (result and not result.success) else None
    result_valid = bool(result and result.success and "error" not in (result.observation or {}))
    reference_verified = bool(result and result.success and (result.observation or {}).get("verified") is True)
    return {
        "expectation": expectation,
        "requested": needs_remote,
        "authorized": authorized,
        "capability_ready": capability_ready,
        "called": called,
        "error_code": error_code,
        "result_valid": result_valid,
        "reference_verified": reference_verified,
        "artifact_published": artifact_published,
    }


# ---------------------------------------------------------------------------
# 1. required + proposed + authorized + MCP success -> succeeded_with_wolfram
# ---------------------------------------------------------------------------


def test_practice_wolfram_required_success_publishes_set(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _science_lesson(pg_db, monkeypatch)
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    artifact = {"items": [controlled.scientific_item("q1", needs_remote=True)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage())]))
    spy, captured = _spying_verifier("verified")
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)

    assert _run_generation(pg_db, settings, job) is None
    assert pgsupport.q_practice_job(pg_db, job.id)["status"] == "succeeded"
    run = pgsupport.q_run(pg_db, practice_job_id=job.id, role="exercise_author")
    assert any(t["tool_name"] == "VerifyScientificAnswer" and t["status"] == "succeeded"
               for t in pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"]))

    facts = _science_facts(pg_db, job, expectation="required", needs_remote=True,
                           captured=captured, authorized=True, capability_ready=True)
    assert report.classify_science_tool_run(facts) == "succeeded_with_wolfram"


# ---------------------------------------------------------------------------
# 2. optional / local -> succeeded_without_wolfram (zero remote call)
# ---------------------------------------------------------------------------


def test_practice_wolfram_optional_local_no_remote_call(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _science_lesson(pg_db, monkeypatch, mode="auto")
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    # needs_remote=False: a local numeric answer; the verifier must NOT be called.
    artifact = {"items": [controlled.scientific_item("q1", needs_remote=False)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage())]))
    spy, captured = _spying_verifier("verified")
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)

    assert _run_generation(pg_db, settings, job) is None
    assert "result" not in captured  # zero remote call
    facts = _science_facts(pg_db, job, expectation="optional", needs_remote=False,
                           captured=captured, authorized=True, capability_ready=True)
    assert report.classify_science_tool_run(facts) == "succeeded_without_wolfram"


# ---------------------------------------------------------------------------
# 3. required sample but the model did NOT request the tool -> tool_request_missed
# ---------------------------------------------------------------------------


def test_practice_wolfram_required_repairs_missing_tool_request(pg_db, monkeypatch):
    """A require_science request cannot silently publish a locally claimed
    answer. It receives one bounded reference repair and is then verified."""
    settings, job, chunk, doc, ver = _science_lesson(pg_db, monkeypatch)
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    artifact = {"items": [controlled.scientific_item("q1", needs_remote=False)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage()),
                                                     (controlled.scientific_repair_dto("q1"), controlled.usage())]))
    spy, captured = _spying_verifier("verified")
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)

    assert _run_generation(pg_db, settings, job) is None
    assert "result" in captured
    facts = _science_facts(pg_db, job, expectation="required", needs_remote=True,
                           captured=captured, authorized=True, capability_ready=True)
    assert report.classify_science_tool_run(facts) == "succeeded_with_wolfram"


# ---------------------------------------------------------------------------
# 4. capability unavailable -> create_generation_job refuses (capability_unavailable)
# ---------------------------------------------------------------------------


def test_practice_wolfram_capability_unavailable_refuses_job(pg_db, monkeypatch):
    """When the science capability projection is not ready, authorizing a
    require_science Job is refused at creation with science_computation_unavailable
    — never silently run without the tool (Spec 004 §6.2)."""
    ws, course, cv, section, lesson, lv, doc, ver, chunk = pgsupport.seed_practice_lesson(
        pg_db, math=True, computable=True)
    settings = pgsupport._make_settings(wolfram_mcp_enabled=True)
    pgsupport.patch_capability_projection(monkeypatch, science_ok=False)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    payload = pgsupport.gen_payload(item_count=1, mode="require_science", science_tool_authorized=True)
    with pytest.raises(ValueError, match="science_computation_unavailable"):
        pgsupport.create_running_generation_job(pg_db, settings, ws, course, cv, lesson, lv, payload=payload)
    assert report.classify_science_tool_run({
        "expectation": "required", "requested": True, "authorized": True,
        "capability_ready": False, "called": False}) == "capability_unavailable"


# ---------------------------------------------------------------------------
# 5. requested + authorized but the tool stage fails -> call-failed categories
#    (schema_drift / mcp_connection_failed / tool_result_invalid)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("policy,error_code,expected_category", [
    ("fail", "schema_drift", "schema_drift"),
    ("fail", "mcp_connection_failed", "mcp_connection_failed"),
    ("invalid_result", "tool_call_error", "tool_result_invalid"),
])
def test_practice_wolfram_tool_stage_failure_classifies_stably(
        pg_db, monkeypatch, policy, error_code, expected_category):
    settings, job, chunk, doc, ver = _science_lesson(pg_db, monkeypatch)
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    artifact = {"items": [controlled.scientific_item("q1", needs_remote=True)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage()),
                                                     (controlled.scientific_repair_dto("q1"), controlled.usage())]))
    spy, captured = _spying_verifier(policy, error_code=error_code)
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)

    code = _run_generation(pg_db, settings, job)
    assert code is not None  # Job failed
    assert pgsupport.q_set(pg_db, job.id) is None  # zero half-finished Set
    # A stable science failure code is surfaced (the private sub-code is
    # intentionally NOT persisted) — never faked as a Wolfram pass.
    assert code in {"science_tool_unavailable", "scientific_reference_unverified",
                    "scientific_repair_revalidation_failed"}, code
    assert controlled.CONTROLLED_BACKEND is True  # never real Wolfram
    facts = _science_facts(pg_db, job, expectation="required", needs_remote=True,
                           captured=captured, authorized=True, capability_ready=True)
    assert report.classify_science_tool_run(facts) == expected_category


# ---------------------------------------------------------------------------
# 6. tool succeeded but reference NOT verified -> scientific_reference_unverified
# ---------------------------------------------------------------------------


def test_practice_wolfram_tool_succeeded_but_reference_unverified(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _science_lesson(pg_db, monkeypatch)
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    artifact = {"items": [controlled.scientific_item("q1", needs_remote=True)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage()),
                                                     (controlled.scientific_repair_dto("q1"), controlled.usage())]))
    spy, captured = _spying_verifier("not_verified")  # success, but says not-equivalent
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)

    code = _run_generation(pg_db, settings, job)
    assert code is not None
    assert pgsupport.q_set(pg_db, job.id) is None
    assert code in {"scientific_reference_unverified", "scientific_repair_revalidation_failed"}, code
    facts = _science_facts(pg_db, job, expectation="required", needs_remote=True,
                           captured=captured, authorized=True, capability_ready=True)
    assert report.classify_science_tool_run(facts) == "scientific_reference_unverified"


# ---------------------------------------------------------------------------
# 7. forbidden negative control -> zero science item, zero tool call
# ---------------------------------------------------------------------------


def test_practice_wolfram_forbidden_negative_zero_tool_call(pg_db, monkeypatch):
    """A concept lesson (no computable target) under require_science is rejected
    at type suitability (in execute_generation) with zero tool calls; the
    baseline classifies it tool_not_needed."""
    ws, course, cv, section, lesson, lv, doc, ver, chunk = pgsupport.seed_practice_lesson(pg_db)
    settings = pgsupport._make_settings()
    pgsupport.patch_capability_projection(monkeypatch, science_ok=False)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    payload = pgsupport.gen_payload(item_count=1, mode="require_science")
    job = pgsupport.create_running_generation_job(pg_db, settings, ws, course, cv, lesson, lv, payload=payload)
    # Suitability is enforced inside execute_generation (capability not ready on a
    # concept lesson -> require_science rejected, before any provider/tool call).
    with pytest.raises(ValueError, match="science_item_not_supported_by_lesson"):
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.rollback()
    assert pgsupport.q_set(pg_db, job.id) is None
    assert report.classify_science_tool_run({
        "expectation": "forbidden", "called": False}) == "tool_not_needed"


# ---------------------------------------------------------------------------
# 8-9. Grading: local-sufficient -> zero call; needs-remote -> Wolfram call
# ---------------------------------------------------------------------------


def _generate_science_set(pg_db, monkeypatch, *, needs_remote):
    settings, job, chunk, doc, ver = _science_lesson(
        pg_db, monkeypatch, mode="require_science" if needs_remote else "auto"
    )
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    artifact = {"items": [controlled.scientific_item("q1", needs_remote=needs_remote)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage())]))
    if needs_remote:
        monkeypatch.setattr("learn_platform_api.services.science_tool_service.execute_science_verification",
                            controlled.make_science_verifier("verified"))
    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()
    ps = pgsupport.q_set(pg_db, job.id)
    item = pg_db.scalar(select(PracticeItem).where(PracticeItem.practice_set_id == ps["id"]))
    return settings, item


def test_practice_grading_local_sufficient_zero_wolfram(pg_db, monkeypatch):
    settings, item = _generate_science_set(pg_db, monkeypatch, needs_remote=False)
    pgsupport.patch_capability_projection(monkeypatch, science_ok=True)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    attempt = practice.submit_attempt(pg_db, settings, item.workspace_id, item.id,
                                      type("A", (), {"external_processing_ack": True, "text": "42",
                                                     "option_key": None, "source_code": None,
                                                     "science_tool_authorized": False})(), "g-local")
    grade_job = pg_db.get(practice.PracticeJob, attempt.practice_job_id)
    grade_job.status = "running"; grade_job.worker_id = "w"
    grade_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    pg_db.commit()
    spy, captured = _spying_verifier("verified")
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)
    monkeypatch.setattr(practice_generation, "call_provider",
                        controlled.ScriptedProvider([({"verdict": "correct", "score": 100,
                                                       "criterion_results": [], "blocks": []}, controlled.usage())]))
    practice_generation.execute_grading(pg_db, settings, grade_job, worker_id="w")
    pg_db.commit()
    assert "result" not in captured  # local rule sufficient -> zero Wolfram during grading


def test_practice_grading_needs_remote_calls_wolfram(pg_db, monkeypatch):
    settings, item = _generate_science_set(pg_db, monkeypatch, needs_remote=True)
    pgsupport.patch_capability_projection(monkeypatch, science_ok=True)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    attempt = practice.submit_attempt(pg_db, settings, item.workspace_id, item.id,
                                      type("A", (), {"external_processing_ack": True, "text": "x^3/3",
                                                     "option_key": None, "source_code": None,
                                                     "science_tool_authorized": True})(), "g-remote")
    grade_job = pg_db.get(practice.PracticeJob, attempt.practice_job_id)
    grade_job.status = "running"; grade_job.worker_id = "w"
    grade_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    pg_db.commit()
    spy, captured = _spying_verifier("verified")
    import learn_platform_api.services.science_tool_service as sci
    monkeypatch.setattr(sci, "execute_science_verification", spy)
    monkeypatch.setattr(practice_generation, "call_provider",
                        controlled.ScriptedProvider([({"verdict": "correct", "score": 100,
                                                       "criterion_results": [], "blocks": []}, controlled.usage())]))
    practice_generation.execute_grading(pg_db, settings, grade_job, worker_id="w")
    pg_db.commit()
    assert "result" in captured  # remote verification was actually invoked during grading
    run = pgsupport.q_run(pg_db, practice_job_id=grade_job.id)
    assert any("VerifyScientificAttempt" in t["tool_name"] for t in pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"]))
