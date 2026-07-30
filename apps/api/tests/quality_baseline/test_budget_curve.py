"""Total-item-count budget curve (Section 8).

Drives the REAL ``execute_generation`` orchestration on throwaway Postgres for
``general_only`` / ``require_coding`` / ``require_science`` at total item counts
``1/3/5/10``. ``item_count`` is the Set total; ``require_coding`` /
``require_science`` only require the corresponding specialized item to EXIST (at
most one per Set); the rest are general items. The matrix is keyed on TOTAL item
count — there is no fabricated "coding item count" parameter (packet §5.2/§8).

Asserts: exact final count on success; ≤1 specialized item per Set; budget
exhaustion uses the stable ``practice_budget_exceeded`` with ZERO half-finished
Set; a length finish-reason triggers the budget; the output limit is per
provider call rather than an already-paid cumulative-output rejection; silent reduction is auditable
(requested vs final recorded distinctly, never relabeled); and the budget
settings are not modified by the run.
"""

from __future__ import annotations

import pytest

from learn_platform_api.services import practice_generation

from quality_baseline import controlled, pgsupport

COUNTS = [1, 3, 5, 10]


def _set_artifact(mode: str, count: int, language: str = "python") -> dict:
    """A legal artifact with exactly ``count`` items: one specialized item for
    require_coding/require_science (when count >= 1) plus general items."""
    items: list[dict] = []
    if mode == "require_coding":
        items.append(controlled.coding_item("q_spec", language, task="identity"))
        items.extend(controlled.general_items(count - 1))
    elif mode == "require_science":
        # require_science now guarantees an authorized reference-verification
        # call; the controlled verifier keeps this matrix deterministic.
        items.append(controlled.scientific_item("q_spec", needs_remote=True))
        items.extend(controlled.general_items(count - 1))
    else:  # general_only
        items = controlled.general_items(count)
    return {"items": items}


def _prepare(pg_db, monkeypatch, mode, count):
    if mode == "require_coding":
        return pgsupport.prepare_budget_job(pg_db, monkeypatch, mode=mode, item_count=count,
                                            language="python", code_auth=True,
                                            algorithmic=True, executable=True)
    if mode == "require_science":
        return pgsupport.prepare_budget_job(pg_db, monkeypatch, mode=mode, item_count=count,
                                            science_auth=True, science_enabled=True,
                                            math=True, computable=True)
    return pgsupport.prepare_budget_job(pg_db, monkeypatch, mode=mode, item_count=count)


def _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, *, responses, code_backend=True):
    pgsupport.patch_evidence(monkeypatch, chunk, doc, ver)
    monkeypatch.setattr(practice_generation, "call_practice_provider",
                        controlled.ScriptedProvider(responses))
    if code_backend:
        monkeypatch.setattr(practice_generation, "execute_code_run_sync",
                            controlled.controlled_execute_code_run_sync)
    if job.item_type_mode == "require_science":
        monkeypatch.setattr(
            "learn_platform_api.services.science_tool_service.execute_science_verification",
            controlled.make_science_verifier("verified"),
        )


# ---------------------------------------------------------------------------
# 1. Success matrix: exact final count, <=1 specialized, plan+generation phases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["general_only", "require_coding", "require_science"])
@pytest.mark.parametrize("count", COUNTS)
def test_budget_curve_success_exact_count(pg_db, monkeypatch, mode, count):
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, mode, count)
    responses = [(controlled.practice_plan(), controlled.usage()),
                 (_set_artifact(mode, count), controlled.usage())]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses)

    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()

    assert pgsupport.q_practice_job(pg_db, job.id)["status"] == "succeeded"
    ps = pgsupport.q_set(pg_db, job.id)
    # Exact final count == requested total (item_count is the Set TOTAL).
    assert ps["item_count"] == count
    assert ps["item_count_actual"] == count
    assert ps["specialized_count"] <= 1
    if mode == "require_coding":
        assert ps["specialized_count"] == 1
        assert ps["item_type_counts"]["coding"] == 1
    elif mode == "require_science":
        assert ps["specialized_count"] == 1
        assert ps["item_type_counts"]["scientific"] == 1
    else:
        assert ps["specialized_count"] == 0
    run = pgsupport.q_run(pg_db, practice_job_id=job.id, role="exercise_author")
    calls = pgsupport.q_provider_calls(pg_db, agent_run_id=run["id"])
    assert [c["phase"] for c in calls] == ["plan", "generation"]
    assert all(c["status"] == "succeeded" and c["input_tokens"] is not None for c in calls)


def test_specialized_item_never_exceeds_one_at_high_count(pg_db, monkeypatch):
    """item_count=10 require_coding must yield exactly ONE coding item + 9 general,
    never multiple specialized items (Spec 005 §6.1, ADR 007 §3.3)."""
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "require_coding", 10)
    responses = [(controlled.practice_plan(), controlled.usage()),
                 (_set_artifact("require_coding", 10), controlled.usage())]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses)
    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()
    ps = pgsupport.q_set(pg_db, job.id)
    assert ps["specialized_count"] == 1
    assert ps["item_type_counts"]["coding"] == 1
    assert sum(ps["item_type_counts"].values()) == 10


def test_multiple_specialized_items_are_rejected(pg_db, monkeypatch):
    """Counterfactual: a provider returning TWO coding items must be rejected
    (at-most-one specialized item), never silently published."""
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "require_coding", 2)
    bad_artifact = {"items": [
        controlled.coding_item("q_a", "python", task="identity"),
        controlled.coding_item("q_b", "python", task="reverse"),
    ]}
    responses = [(controlled.practice_plan(), controlled.usage()),
                 (bad_artifact, controlled.usage()),
                 (bad_artifact, controlled.usage())]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses)
    with pytest.raises(ValueError):
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.rollback()
    assert pgsupport.q_set(pg_db, job.id) is None


# ---------------------------------------------------------------------------
# 2. Budget exhaustion: length finish-reason -> practice_budget_exceeded, zero Set
# ---------------------------------------------------------------------------


def test_budget_exhausted_via_length_finish_reason(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "general_only", 10)
    # Generation call returns finish_reason="length" -> practice_budget_exceeded.
    responses = [(controlled.practice_plan(), controlled.usage()),
                 (_set_artifact("general_only", 10), controlled.usage(finish_reason="length"))]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses, code_backend=False)
    with pytest.raises(ValueError, match="practice_budget_exceeded"):
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.rollback()
    assert pgsupport.q_set(pg_db, job.id) is None  # zero half-finished Set


def test_output_limit_is_per_provider_call_not_cumulative(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "general_only", 1)
    per_call = settings.practice_generation_max_output_tokens
    responses = [
        (
            controlled.practice_plan(),
            controlled.usage(output_tokens=settings.product_generation_max_output_tokens - 1),
        ),
        (_set_artifact("general_only", 1), controlled.usage(output_tokens=per_call - 1)),
    ]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses, code_backend=False)

    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()

    assert pgsupport.q_practice_job(pg_db, job.id)["status"] == "succeeded"
    assert pgsupport.q_set(pg_db, job.id)["item_count"] == 1


def test_single_provider_call_over_output_limit_is_rejected(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "general_only", 1)
    responses = [
        (
            controlled.practice_plan(),
            controlled.usage(output_tokens=settings.practice_generation_max_output_tokens + 1),
        ),
    ]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses, code_backend=False)

    with pytest.raises(ValueError, match="practice_budget_exceeded"):
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.rollback()

    assert pgsupport.q_set(pg_db, job.id) is None


# ---------------------------------------------------------------------------
# 3. Failure phase is classifiable: an invalid artifact -> stable structure code
# ---------------------------------------------------------------------------


def test_budget_curve_failure_phase_is_classifiable(pg_db, monkeypatch):
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "general_only", 3)
    invalid = {"items": [{"item_key": "x", "target_key": "objective_1", "item_type": "single_choice",
                          "stem": "s", "citation_ids": ["eUNKNOWN"],
                          "options": [{"option_key": "a", "text": "A", "is_correct": True, "rationale": "r", "citation_ids": ["eUNKNOWN"]},
                                      {"option_key": "b", "text": "B", "is_correct": False, "rationale": "r", "citation_ids": ["eUNKNOWN"]}]}]}
    responses = [(controlled.practice_plan(), controlled.usage()),
                 (invalid, controlled.usage()),
                 (invalid, controlled.usage())]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses, code_backend=False)
    with pytest.raises(ValueError) as exc:
        practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    code = str(exc.value)
    pg_db.rollback()
    # A stable structure/citation code, classified to a phase — not an unknown.
    assert code in {"practice_citation_invalid", "practice_artifact_schema_invalid"}, code
    assert pgsupport.q_set(pg_db, job.id) is None


# ---------------------------------------------------------------------------
# 4. Silent reduction is AUDITABLE, not hidden (requested vs final recorded)
# ---------------------------------------------------------------------------


def test_silent_reduction_is_auditable_not_relabelled(pg_db, monkeypatch):
    """If a scripted provider returns FEWER items than requested, the published
    Set's ``item_count`` equals the ACTUAL count (not the requested), while the
    generation_config records the requested count — so a reduction is always
    visible in authoritative facts and is never relabelled as the full request
    (packet §8: no silent reduction faking success)."""
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "general_only", 10)
    fewer = _set_artifact("general_only", 5)  # provider silently returns 5, not 10
    responses = [(controlled.practice_plan(), controlled.usage()), (fewer, controlled.usage())]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses, code_backend=False)
    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()
    ps = pgsupport.q_set(pg_db, job.id)
    # The authoritative Set count is the ACTUAL 5, and the requested 10 is kept
    # separately in generation_config — the discrepancy is auditable.
    assert ps["item_count"] == 5
    assert ps["generation_config"]["item_count"] == 10
    assert ps["item_count"] != ps["generation_config"]["item_count"]


# ---------------------------------------------------------------------------
# 5. Budget settings are not modified by a run
# ---------------------------------------------------------------------------


def _budget_snapshot(settings) -> dict:
    """The authoritative budget denominations that must not move during a run."""
    return {
        "max_provider_calls": settings.practice_generation_max_provider_calls,
        "max_attempt_steps": settings.practice_generation_max_attempt_steps,
        "max_searches": settings.practice_generation_max_searches,
    }


def test_budget_settings_are_not_modified(pg_db, monkeypatch):
    """The ACTUAL settings object handed to ``execute_generation`` must keep its
    budget fields unchanged across the run. Comparing two independent ``Settings()``
    defaults is a false positive: it never observes the run, so a mutation would
    pass silently. Here we spy on ``execute_generation`` to capture the exact
    object, snapshot it before the body runs, and re-assert the SAME object
    afterward (packet Fix 3)."""
    settings, job, chunk, doc, ver = _prepare(pg_db, monkeypatch, "require_coding", 5)
    responses = [(controlled.practice_plan(), controlled.usage()),
                 (_set_artifact("require_coding", 5), controlled.usage())]
    _wire(pg_db, monkeypatch, settings, job, chunk, doc, ver, responses=responses)

    captured: dict = {}
    real_execute = practice_generation.execute_generation

    def spy(db, s, j, *, worker_id=None):
        # Observe the real execution object: snapshot its budget fields before
        # the orchestration body touches it.
        captured["settings"] = s
        captured["before"] = _budget_snapshot(s)
        return real_execute(db, s, j, worker_id=worker_id)

    monkeypatch.setattr(practice_generation, "execute_generation", spy)
    practice_generation.execute_generation(pg_db, settings, job, worker_id="test-worker")
    pg_db.commit()

    # The object actually passed in is the one we configured (not a copy).
    assert captured["settings"] is settings
    # The SAME object's budget fields are unchanged after the run.
    assert _budget_snapshot(captured["settings"]) == captured["before"]
    # v2 unified budget denominations (Spec 005 §7.2 / ADR 007 §3.6) hold.
    assert captured["before"]["max_provider_calls"] == 4
    assert captured["before"]["max_attempt_steps"] == 12
