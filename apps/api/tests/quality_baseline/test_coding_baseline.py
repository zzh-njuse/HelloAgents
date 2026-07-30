"""Three-language coding baseline (Section 7).

Every scenario drives the REAL ``practice_generation.execute_generation`` /
``execute_grading`` orchestration on a throwaway Postgres database, with only the
lowest-level seams replaced: the LLM provider, retrieval, and the execution-MCP
backend. The execution backend (``controlled_execute_code_run_sync``) runs the
REAL product coding harness (``_build_coding_harness_for_version``) on the REAL
local ``python``/``javac``/``g++`` toolchain — so canonical wrapper/entrypoint,
UTF-8, multiline I/O and compile/runtime classification are genuinely exercised.
It is a CONTROLLED backend (``controlled_backend``), never the real Judge0 VM
(Spec 007 §9.1, packet §7.2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learn_platform_api.db.models import PracticeItem
from learn_platform_api.services import practice, practice_generation
from sqlalchemy import select

from quality_baseline import controlled, pgsupport, samples

LANGUAGES = ["python", "java", "cpp"]


# ---------------------------------------------------------------------------
# Generation driver
# ---------------------------------------------------------------------------


def _coding_sample_for(language):
    return {"python": samples.PRACTICE_CODING_IDENTITY,
            "java": samples.PRACTICE_CODING_REVERSE,
            "cpp": samples.PRACTICE_CODING_AGGREGATE}[language]


def _task_for(language):
    return "identity" if language in ("python", "cpp") else "reverse"


def _correct_source(language):
    task = _task_for(language)
    return controlled._identity_source(language) if task == "identity" else controlled._reverse_source(language)


# ---------------------------------------------------------------------------
# 1. Initial success per language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_coding_initial_success_publishes_set(pg_db, monkeypatch, language):
    sample = _coding_sample_for(language)
    # Re-seed with this sample's profile + language directly.
    settings, job, chunk, doc, ver = pgsupport.prepare_generation(
        pg_db, monkeypatch, sample=sample, code_auth=True)
    # prepare_generation used sample.language already; ensure the job's language matches.
    pg_db.commit()
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    task = "identity" if language in ("python", "cpp") else "reverse"
    artifact = {"items": [controlled.coding_item("q1", language, task=task)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage())]))
    monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                        controlled.controlled_execute_code_run_sync)

    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()

    assert pgsupport.q_practice_job(pg_db, job.id)["status"] == "succeeded"
    ps = pgsupport.q_set(pg_db, job.id)
    assert ps["item_type_counts"] == {"coding": 1}
    assert ps["specialized_count"] == 1
    assert ps["coding_languages"] == [language]
    run = pgsupport.q_run(pg_db, practice_job_id=job.id, role="exercise_author")
    assert run["status"] == "succeeded"
    tools = pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"])
    assert any(t["tool_name"] == "ValidateCodingReference" and t["status"] == "succeeded" for t in tools)
    calls = pgsupport.q_provider_calls(pg_db, agent_run_id=run["id"])
    assert [c["phase"] for c in calls] == ["plan", "generation"]
    assert all(c["status"] == "succeeded" for c in calls)


# ---------------------------------------------------------------------------
# 2. Specialized repair success per language (initial broken → repair fixed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_coding_specialized_repair_success(pg_db, monkeypatch, language):
    sample = _coding_sample_for(language)
    settings, job, chunk, doc, ver = pgsupport.prepare_generation(
        pg_db, monkeypatch, sample=sample, code_auth=True)
    pg_db.commit()
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    task = "identity" if language in ("python", "cpp") else "reverse"
    correct = controlled._identity_source(language) if task == "identity" else controlled._reverse_source(language)
    broken = controlled.wrong_output_source(language, task)
    artifact = {"items": [controlled.coding_item("q1", language, task=task, reference_solution=broken)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([
                            (controlled.practice_plan(), controlled.usage()),
                            (artifact, controlled.usage()),
                            (controlled.coding_repair_dto("q1", correct), controlled.usage()),
                        ]))
    monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                        controlled.controlled_execute_code_run_sync)

    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()

    assert pgsupport.q_practice_job(pg_db, job.id)["status"] == "succeeded"
    ps = pgsupport.q_set(pg_db, job.id)
    assert ps is not None and ps["item_type_counts"] == {"coding": 1}
    run = pgsupport.q_run(pg_db, practice_job_id=job.id, role="exercise_author")
    calls = pgsupport.q_provider_calls(pg_db, agent_run_id=run["id"])
    assert [c["phase"] for c in calls] == ["plan", "generation", "repair"]
    # Repair revalidation must have passed.
    tools = pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"])
    assert any(t["tool_name"] == "RepairSpecializedItem" and t["status"] == "succeeded" for t in tools)


# ---------------------------------------------------------------------------
# 2b. Canonical source-shape repair before execution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_coding_source_contract_failure_uses_specialized_repair(
        pg_db, monkeypatch, language):
    sample = _coding_sample_for(language)
    settings, job, chunk, doc, ver = pgsupport.prepare_generation(
        pg_db, monkeypatch, sample=sample, code_auth=True)
    pg_db.commit()
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    task = _task_for(language)
    correct = _correct_source(language)
    malformed = {
        "python": "def answer(value):\n    return value",
        "java": "class Answer { static String answer(String input) { return input; } }",
        "cpp": "std::string answer(const std::string& input){ return input; }",
    }[language]
    artifact = {"items": [controlled.coding_item(
        "q1", language, task=task, reference_solution=malformed
    )]}
    monkeypatch.setattr(
        practice_generation,
        "call_practice_provider",
        controlled.ScriptedProvider([
            (controlled.practice_plan(), controlled.usage()),
            (artifact, controlled.usage()),
            (controlled.coding_repair_dto("q1", correct), controlled.usage()),
        ]),
    )
    monkeypatch.setattr(
        practice_generation,
        "execute_code_run_sync",
        controlled.controlled_execute_code_run_sync,
    )

    practice_generation.execute_generation(
        pg_db, settings, job, worker_id="test-worker"
    )
    pg_db.commit()

    assert pgsupport.q_practice_job(pg_db, job.id)["status"] == "succeeded"
    run = pgsupport.q_run(
        pg_db, practice_job_id=job.id, role="exercise_author"
    )
    calls = pgsupport.q_provider_calls(pg_db, agent_run_id=run["id"])
    assert [call["phase"] for call in calls] == ["plan", "generation", "repair"]
    tools = pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"])
    assert any(
        call["tool_name"] == "RepairSpecializedItem"
        and call["status"] == "succeeded"
        for call in tools
    )


# ---------------------------------------------------------------------------
# 3. Reference compile failure (java/cpp) — broken initial AND broken repair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["java", "cpp"])
def test_coding_reference_compile_failure_rejects_set(pg_db, monkeypatch, language):
    """A reference that genuinely fails to compile must reject the Set with a
    stable coding-reference code and leave ZERO half-finished Set (Spec 005 §5,
    ADR 007 §3.4). Counterfactual: the broken reference must fail the chain."""
    sample = _coding_sample_for(language)
    settings, job, chunk, doc, ver = pgsupport.prepare_generation(
        pg_db, monkeypatch, sample=sample, code_auth=True)
    pg_db.commit()
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    broken = controlled.compile_error_source(language)
    artifact = {"items": [controlled.coding_item("q1", language, task="identity", reference_solution=broken)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([
                            (controlled.practice_plan(), controlled.usage()),
                            (artifact, controlled.usage()),
                            (controlled.coding_repair_dto("q1", broken), controlled.usage()),
                        ]))
    monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                        controlled.controlled_execute_code_run_sync)

    with pytest.raises(ValueError) as exc:
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    code = str(exc.value)
    pg_db.rollback()

    assert "coding_reference_compile_failed" in code or "coding_repair_revalidation_failed" in code, code
    assert pgsupport.q_set(pg_db, job.id) is None  # zero half-finished Set


# ---------------------------------------------------------------------------
# 4. Reference test mismatch per language — compiles but wrong output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_coding_reference_test_mismatch_rejects_set(pg_db, monkeypatch, language):
    sample = _coding_sample_for(language)
    settings, job, chunk, doc, ver = pgsupport.prepare_generation(
        pg_db, monkeypatch, sample=sample, code_auth=True)
    pg_db.commit()
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    task = "identity" if language in ("python", "cpp") else "reverse"
    wrong = controlled.wrong_output_source(language, task)
    artifact = {"items": [controlled.coding_item("q1", language, task=task, reference_solution=wrong)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([
                            (controlled.practice_plan(), controlled.usage()),
                            (artifact, controlled.usage()),
                            (controlled.coding_repair_dto("q1", wrong), controlled.usage()),
                        ]))
    monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                        controlled.controlled_execute_code_run_sync)

    with pytest.raises(ValueError) as exc:
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    code = str(exc.value)
    pg_db.rollback()

    assert "coding_reference_test_failed" in code or "coding_repair_revalidation_failed" in code, code
    assert pgsupport.q_set(pg_db, job.id) is None


# ---------------------------------------------------------------------------
# 5. Grading: correct submission scores 100, representative wrong scores 0
# ---------------------------------------------------------------------------


def _generate_published_coding_set(pg_db, monkeypatch, language):
    sample = _coding_sample_for(language)
    settings, job, chunk, doc, ver = pgsupport.prepare_generation(
        pg_db, monkeypatch, sample=sample, code_auth=True)
    pg_db.commit()
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    task = "identity" if language in ("python", "cpp") else "reverse"
    artifact = {"items": [controlled.coding_item("q1", language, task=task)]}
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider([(controlled.practice_plan(), controlled.usage()),
                                                     (artifact, controlled.usage())]))
    monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                        controlled.controlled_execute_code_run_sync)
    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()
    ps = pgsupport.q_set(pg_db, job.id)
    item = pg_db.scalar(select(PracticeItem).where(PracticeItem.practice_set_id == ps["id"]))
    return settings, item, task


def _grade(pg_db, monkeypatch, settings, item, source_code, idem):
    pgsupport.patch_capability_projection(monkeypatch, code_ok=True)
    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_a: None)
    attempt = practice.submit_attempt(pg_db, settings, item.workspace_id, item.id,
                                      type("A", (), {"external_processing_ack": True, "source_code": source_code,
                                                     "option_key": None, "text": None,
                                                     "science_tool_authorized": False})(), idem)
    grade_job = pg_db.get(practice.PracticeJob, attempt.practice_job_id)
    grade_job.status = "running"; grade_job.worker_id = "test-worker"
    grade_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    pg_db.commit()
    monkeypatch.setattr(practice_generation, "call_provider",
                        controlled.ScriptedProvider([({"verdict": "ok", "score": 0,
                                                       "criterion_results": [], "blocks": []}, controlled.usage())]))
    monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                        controlled.controlled_execute_code_run_sync)
    practice_generation.execute_grading(pg_db, settings, grade_job, worker_id="test-worker")
    pg_db.commit()
    return attempt


@pytest.mark.parametrize("language", LANGUAGES)
def test_coding_grading_correct_and_wrong_submissions(pg_db, monkeypatch, language):
    settings, item, task = _generate_published_coding_set(pg_db, monkeypatch, language)
    correct = controlled._identity_source(language) if task == "identity" else controlled._reverse_source(language)
    # A constant-wrong submission fails EVERY test (0%); a partially-wrong one
    # would muddy the "representative wrong" baseline, so use the constant form.
    wrong = controlled.wrong_output_source(language, "identity")

    att_ok = _grade(pg_db, monkeypatch, settings, item, correct, f"ok-{language}")
    fb_ok = pgsupport.q_feedback(pg_db, att_ok.id)
    assert fb_ok["score"] == 100 and fb_ok["verdict"] == "correct", fb_ok

    att_bad = _grade(pg_db, monkeypatch, settings, item, wrong, f"bad-{language}")
    fb_bad = pgsupport.q_feedback(pg_db, att_bad.id)
    assert fb_bad["score"] == 0 and fb_bad["verdict"] == "incorrect", fb_bad
    # The coding grading run records a CodeExecution tool call.
    run = pgsupport.q_run(pg_db, practice_job_id=att_bad.practice_job_id, role="answer_grader")
    assert any(t["tool_name"] == "CodeExecution" for t in pgsupport.q_tool_calls(pg_db, agent_run_id=run["id"]))


# ---------------------------------------------------------------------------
# 6. Java/C++ canonical wrapper, UTF-8, multiline IO, compile-error classification
#    through the REAL harness on the REAL toolchain (controlled_backend, not Judge0)
# ---------------------------------------------------------------------------


def _run_harness(language, reference, hidden_tests):
    """Build the REAL v2 harness and run it via the controlled local backend."""
    from academic_companion.practice_agents import HARNESS_V2
    from learn_platform_api.services.practice_generation import _build_coding_harness_for_version
    harness = _build_coding_harness_for_version(reference, hidden_tests, language, HARNESS_V2)
    result, _handshake = controlled.controlled_execute_code_run_sync(
        "req", language, harness, "", None)
    return result


def test_java_canonical_wrapper_normalizes_public_class_and_compiles():
    """``public class Solution`` is rewritten to ``class Solution`` so the
    product-supplied ``class Main`` compiles alongside it (Spec 005 §6.2)."""
    from academic_companion.practice_agents import HARNESS_V2
    from learn_platform_api.services.practice_generation import _build_coding_harness_for_version
    reference = "public class Solution { static String solve(String input) { return input; } }"
    harness = _build_coding_harness_for_version(reference, [
        {"input": "a", "expected_output": "a", "weight": 1}], "java", HARNESS_V2)
    assert "public class Solution" not in harness
    assert "class Solution" in harness
    result = _run_harness("java", reference, [
        {"input": "a", "expected_output": "a", "weight": 1},
        {"input": "b", "expected_output": "b", "weight": 1}])
    assert result.status == "completed"
    assert controlled.json.loads  # sanity
    import json as _json
    parsed = _json.loads(result.stdout.strip())
    assert parsed["passed"] == parsed["total"] == 2


def test_cpp_accepts_bare_string_spelling_and_provider_includes():
    source = ("#include <algorithm>\nusing namespace std;\n"
              "string solve(const string& input){ string s=input; reverse(s.begin(), s.end()); return s; }")
    result = _run_harness("cpp", source, [
        {"input": "abc", "expected_output": "cba", "weight": 1},
        {"input": "x", "expected_output": "x", "weight": 1}])
    assert result.status == "completed"
    import json as _json
    parsed = _json.loads(result.stdout.strip())
    assert parsed["passed"] == 2


def test_utf8_and_multiline_io_round_trip_in_all_languages():
    """UTF-8 (Latin + CJK) and multiline output round-trip through the real harness."""
    for language, source in [
        ("python", "def solve(input_text):\n    return input_text"),
        ("java", "class Solution { static String solve(String input) { return input; } }"),
        ("cpp", "std::string solve(const std::string& input){ return input; }"),
    ]:
        result = _run_harness(language, source, [
            {"input": "héllo", "expected_output": "héllo", "weight": 1},
            {"input": "中文", "expected_output": "中文", "weight": 1},
            {"input": "line1\nline2", "expected_output": "line1 line2", "weight": 1},
        ])
        assert result.status == "completed", (language, result.status, result.stderr)
        import json as _json
        parsed = _json.loads(result.stdout.strip())
        assert parsed["passed"] == 3, (language, parsed)


@pytest.mark.parametrize("language", ["java", "cpp"])
def test_compile_error_is_classified_not_reported_as_judge0(language):
    """A genuine compile error classifies as ``compile_error`` (a student/reference
    program result), and the controlled backend is marked — never reported as a
    real Judge0 pass (Spec 007 §9.1, packet §7.2)."""
    assert controlled.CONTROLLED_BACKEND is True
    broken = controlled.compile_error_source(language)
    result = _run_harness(language, broken, [
        {"input": "a", "expected_output": "a", "weight": 1}])
    assert result.status == "compile_error"
