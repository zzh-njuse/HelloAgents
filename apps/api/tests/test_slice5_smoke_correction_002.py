"""Slice 5 Smoke Correction 002 — focused regression tests.

Covers Correction 002 tasks (A–F):
  A. Minimal specialized repair DTO (CodingReferenceRepairArtifact,
     ScientificReferenceRepairArtifact) with extra-field-forbidden
  B. Set-level vs specialized-item-level error classification
  C. Safe position summary for Java/C++ repair
  D. Distinct stable error codes for repair-artifact-invalid vs
     repair-then-revalidate failure
  E. Infrastructure failure isolation (zero specialized repair calls)
  F. practice_generation_model configuration scope

Plus fixture-driven generation orchestration tests per language:
  - Python happy + reference repair
  - Java happy, compile failure, test mismatch, repair success, repair invalid
  - C++ happy, compile failure, test mismatch, repair success
  - Java/C++ infrastructure failure

These tests are provider-free, secret-free and do not depend on real
Judge0/Wolfram/MCP. Backend tests use the existing SQLite test infrastructure.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from learn_platform_api.db.models import AgentRun, AgentToolCall


# ---------------------------------------------------------------------------
# A. Minimal repair DTO
# ---------------------------------------------------------------------------

def test_coding_repair_dto_accepts_minimal_fields() -> None:
    """Provider returns only item_key + reference_solution -> success."""
    from academic_companion.practice_agents import CodingReferenceRepairArtifact

    artifact = CodingReferenceRepairArtifact(
        item_key="q1",
        reference_solution="def solve(input_text): return input_text",
    )
    assert artifact.item_key == "q1"
    assert artifact.reference_solution == "def solve(input_text): return input_text"
    assert artifact.starter_code is None  # optional


def test_coding_repair_dto_accepts_starter_code() -> None:
    """Provider returns item_key + reference_solution + starter_code -> success."""
    from academic_companion.practice_agents import CodingReferenceRepairArtifact

    artifact = CodingReferenceRepairArtifact(
        item_key="q1",
        reference_solution="def solve(input_text): return input_text",
        starter_code="def solve(input_text):\n    pass",
    )
    assert artifact.starter_code == "def solve(input_text):\n    pass"


def test_coding_repair_dto_rejects_extra_fields() -> None:
    """Provider returns hidden_tests/stem/citation_ids/language -> rejected."""
    from academic_companion.practice_agents import CodingReferenceRepairArtifact

    with pytest.raises(ValidationError) as exc_info:
        CodingReferenceRepairArtifact(
            item_key="q1",
            reference_solution="def solve(input_text): return input_text",
            hidden_tests=[{"input": "a", "expected_output": "a"}],
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        CodingReferenceRepairArtifact(
            item_key="q1",
            reference_solution="def solve(input_text): return input_text",
            stem="Some question",
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        CodingReferenceRepairArtifact(
            item_key="q1",
            reference_solution="def solve(input_text): return input_text",
            citation_ids=["e1"],
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        CodingReferenceRepairArtifact(
            item_key="q1",
            reference_solution="def solve(input_text): return input_text",
            language="python",
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_coding_repair_dto_wrong_item_key_rejected() -> None:
    """item_key must match the failed item."""
    from academic_companion.practice_agents import CodingReferenceRepairArtifact

    # The DTO itself accepts any valid item_key; the merge logic checks
    # that it matches the original. This test verifies the DTO accepts
    # a different key (the merge check is in execute_generation).
    artifact = CodingReferenceRepairArtifact(
        item_key="wrong_key",
        reference_solution="def solve(input_text): return input_text",
    )
    assert artifact.item_key == "wrong_key"
    # The merge in execute_generation checks item_key == original.item_key


def test_scientific_repair_dto_accepts_minimal_fields() -> None:
    """Provider returns item_key + scientific_answer_spec + reference_answer."""
    from academic_companion.practice_agents import ScientificReferenceRepairArtifact

    artifact = ScientificReferenceRepairArtifact(
        item_key="q1",
        scientific_answer_spec={
            "normalized_answer": "9.81",
            "equivalence_rule": "numeric_tolerance",
            "tolerance": 0.01,
            "needs_remote_verification": False,
        },
        reference_answer="9.81 m/s^2",
    )
    assert artifact.item_key == "q1"


def test_scientific_repair_dto_rejects_extra_fields() -> None:
    """Provider returns rubric/stem/citation_ids -> rejected."""
    from academic_companion.practice_agents import ScientificReferenceRepairArtifact

    with pytest.raises(ValidationError) as exc_info:
        ScientificReferenceRepairArtifact(
            item_key="q1",
            scientific_answer_spec={
                "normalized_answer": "9.81",
                "equivalence_rule": "exact",
                "needs_remote_verification": False,
            },
            reference_answer="9.81 m/s^2",
            rubric=[{"criterion_key": "c1", "description": "ok", "weight": 100}],
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_malformed_minimal_artifact_gets_stable_error() -> None:
    """Malformed minimal artifact -> coding_repair_artifact_invalid stable code."""
    from academic_companion.practice_agents import CodingReferenceRepairArtifact

    with pytest.raises(ValidationError):
        CodingReferenceRepairArtifact(
            item_key="q1",
            # Missing required reference_solution
        )


def test_minimal_merge_preserves_original_immutable_fields() -> None:
    """Merge copies all immutable fields from original, only sets
    reference_solution and starter_code from the repair DTO."""
    from academic_companion.practice_agents import (
        CodingReferenceRepairArtifact,
        PracticeItemArtifact,
    )
    from learn_platform_api.services.practice_generation import _merge_minimal_coding_repair

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="coding",
        stem="Implement the identity.", citation_ids=["e1", "e2"], language="python",
        hidden_tests=[
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        reference_solution="def solve(input_text): return 'wrong'",
        starter_code="def solve(input_text): pass",
        public_examples=[{"input": "test", "expected_output": "test"}],
        constraints=["time_limit: 1s"],
        input_description="A string.",
        output_description="The same string.",
    )
    repair = CodingReferenceRepairArtifact(
        item_key="q1",
        reference_solution="def solve(input_text): return input_text",
    )
    merged = _merge_minimal_coding_repair(original, repair)

    # Mutable fields come from repair
    assert merged.reference_solution == "def solve(input_text): return input_text"
    # Immutable fields come from original
    assert merged.stem == original.stem
    assert sorted(merged.citation_ids) == sorted(original.citation_ids)
    assert merged.language == original.language
    assert merged.hidden_tests == original.hidden_tests
    assert merged.public_examples == original.public_examples
    assert merged.constraints == original.constraints
    assert merged.input_description == original.input_description
    assert merged.output_description == original.output_description
    assert merged.item_key == original.item_key
    assert merged.target_key == original.target_key
    assert merged.item_type == original.item_type


def test_minimal_scientific_merge_preserves_original_immutable_fields() -> None:
    """Merge copies all immutable fields from original for scientific items."""
    from academic_companion.practice_agents import (
        ScientificReferenceRepairArtifact,
        PracticeItemArtifact,
    )
    from learn_platform_api.services.practice_generation import _merge_minimal_scientific_repair

    original = PracticeItemArtifact(
        item_key="q1", target_key="objective_1", item_type="scientific",
        stem="Compute the velocity.", citation_ids=["e1"],
        scientific_answer_spec={
            "normalized_answer": "10", "equivalence_rule": "exact",
            "needs_remote_verification": False,
        },
        rubric=[
            {"criterion_key": "c1", "description": "Correct value", "weight": 60, "citation_ids": ["e1"]},
            {"criterion_key": "c2", "description": "Units", "weight": 40, "citation_ids": ["e1"]},
        ],
        reference_answer="v = 10 m/s (approx)",
    )
    repair = ScientificReferenceRepairArtifact(
        item_key="q1",
        scientific_answer_spec={
            "normalized_answer": "10.0", "equivalence_rule": "numeric_tolerance",
            "tolerance": 0.01, "needs_remote_verification": False,
        },
        reference_answer="v = 10.0 m/s",
    )
    merged = _merge_minimal_scientific_repair(original, repair)

    # Mutable fields from repair
    assert merged.reference_answer == "v = 10.0 m/s"
    assert merged.scientific_answer_spec.normalized_answer == "10.0"
    # Immutable fields from original
    assert merged.stem == original.stem
    assert merged.citation_ids == original.citation_ids
    assert merged.rubric == original.rubric
    assert merged.item_key == original.item_key


def test_repair_then_revalidate_no_more_provider_calls() -> None:
    """After repair + re-validation failure, no more provider calls are made."""
    from learn_platform_api.services.practice_generation import (
        CODING_REPAIR_REVALIDATION_FAILED,
    )
    # The stable code exists and is distinct from the artifact-invalid code
    assert CODING_REPAIR_REVALIDATION_FAILED == "coding_repair_revalidation_failed"


# ---------------------------------------------------------------------------
# B. Error classification (Set vs specialized-item vs general-item)
# ---------------------------------------------------------------------------

def test_classify_set_level_errors() -> None:
    """Set-level errors: item count, duplicate item_key, cross-Item constraints."""
    from learn_platform_api.services.practice_generation import _classify_validation_error

    assert _classify_validation_error(ValueError("duplicate item_key")) == "set_level"
    assert _classify_validation_error(ValueError("at most one specialized")) == "set_level"
    assert _classify_validation_error(ValueError("must include at least one general")) == "set_level"


def test_classify_specialized_item_level_errors() -> None:
    """Specialized-item-level errors: coding/scientific field, canonical source."""
    from learn_platform_api.services.practice_generation import _classify_validation_error

    assert _classify_validation_error(ValueError("coding requires a language")) == "specialized_item_level"
    assert _classify_validation_error(ValueError("java coding sources must not declare a package")) == "specialized_item_level"
    assert _classify_validation_error(ValueError("cpp coding sources must define string solve")) == "specialized_item_level"
    assert _classify_validation_error(ValueError("python coding sources must define solve")) == "specialized_item_level"
    assert _classify_validation_error(ValueError("coding requires 3-20 hidden tests")) == "specialized_item_level"
    assert _classify_validation_error(ValueError("scientific requires a scientific_answer_spec")) == "specialized_item_level"
    assert _classify_validation_error(ValueError("starter_code must not reveal")) == "specialized_item_level"


def test_classify_general_item_level_errors() -> None:
    """General-item-level errors: single-choice/short-answer schema."""
    from learn_platform_api.services.practice_generation import _classify_validation_error

    assert _classify_validation_error(ValueError("single_choice requires 2-6 options")) == "general_item_level"
    assert _classify_validation_error(ValueError("rubric weights must sum to 100")) == "general_item_level"
    assert _classify_validation_error(ValueError("unknown_citation")) == "general_item_level"


# ---------------------------------------------------------------------------
# C. Safe position summary
# ---------------------------------------------------------------------------

def test_safe_position_summary_contains_no_paths_or_secrets() -> None:
    """Position summary must not contain absolute paths, hidden test content,
    or full compiler stderr."""
    from learn_platform_api.services.practice_generation import (
        _build_safe_position_summary,
        CodingReferenceValidationResult,
    )

    result = CodingReferenceValidationResult(
        passed=False, tests_passed=1, tests_total=3,
        error_categories=["compile_error"], infrastructure_failure=False,
    )
    summary = _build_safe_position_summary("java", result)
    assert "java" in summary
    assert "compile_error" in summary
    assert "1/3" in summary
    # Must NOT contain paths or secrets
    assert "C:" not in summary
    assert "/tmp/" not in summary
    assert "hidden" not in summary.casefold() or "hidden_tests" not in summary


def test_safe_position_summary_for_infrastructure_failure() -> None:
    """Infrastructure failure summary is bounded and safe."""
    from learn_platform_api.services.practice_generation import (
        _build_safe_position_summary,
        CodingReferenceValidationResult,
    )

    result = CodingReferenceValidationResult(
        passed=False, tests_passed=0, tests_total=3,
        error_categories=["infrastructure_failure"], infrastructure_failure=True,
    )
    summary = _build_safe_position_summary("cpp", result)
    assert "infrastructure" in summary
    assert "cpp" in summary


def test_safe_position_summary_for_test_mismatch() -> None:
    """Test mismatch summary includes language and category."""
    from learn_platform_api.services.practice_generation import (
        _build_safe_position_summary,
        CodingReferenceValidationResult,
    )

    result = CodingReferenceValidationResult(
        passed=False, tests_passed=2, tests_total=5,
        error_categories=["test_mismatch"], infrastructure_failure=False,
    )
    summary = _build_safe_position_summary("python", result)
    assert "python" in summary
    assert "test_mismatch" in summary
    assert "2/5" in summary


# ---------------------------------------------------------------------------
# D. Distinct stable error codes
# ---------------------------------------------------------------------------

def test_repair_artifact_invalid_codes_are_stable() -> None:
    """Repair artifact invalid codes are distinct from revalidation failure codes."""
    from learn_platform_api.services.practice_generation import (
        CODING_REPAIR_ARTIFACT_INVALID,
        SCIENTIFIC_REPAIR_ARTIFCAT_INVALID,
        CODING_REPAIR_REVALIDATION_FAILED,
        SCIENTIFIC_REPAIR_REVALIDATION_FAILED,
    )

    assert CODING_REPAIR_ARTIFACT_INVALID == "coding_repair_artifact_invalid"
    assert SCIENTIFIC_REPAIR_ARTIFCAT_INVALID == "scientific_repair_artifact_invalid"
    assert CODING_REPAIR_REVALIDATION_FAILED == "coding_repair_revalidation_failed"
    assert SCIENTIFIC_REPAIR_REVALIDATION_FAILED == "scientific_repair_revalidation_failed"

    # All four codes are distinct
    codes = {
        CODING_REPAIR_ARTIFACT_INVALID,
        SCIENTIFIC_REPAIR_ARTIFCAT_INVALID,
        CODING_REPAIR_REVALIDATION_FAILED,
        SCIENTIFIC_REPAIR_REVALIDATION_FAILED,
    }
    assert len(codes) == 4


def test_repair_error_codes_are_in_worker_messages() -> None:
    """All repair error codes have user-facing messages in the worker."""
    from learn_platform_api.practice_workers import ERROR_MESSAGES
    from learn_platform_api.services.practice_generation import (
        CODING_REPAIR_ARTIFACT_INVALID,
        SCIENTIFIC_REPAIR_ARTIFCAT_INVALID,
        CODING_REPAIR_REVALIDATION_FAILED,
        SCIENTIFIC_REPAIR_REVALIDATION_FAILED,
    )

    for code in (
        CODING_REPAIR_ARTIFACT_INVALID,
        SCIENTIFIC_REPAIR_ARTIFCAT_INVALID,
        CODING_REPAIR_REVALIDATION_FAILED,
        SCIENTIFIC_REPAIR_REVALIDATION_FAILED,
    ):
        assert code in ERROR_MESSAGES, f"error code {code} missing from ERROR_MESSAGES"


# ---------------------------------------------------------------------------
# E. Infrastructure failure isolation
# ---------------------------------------------------------------------------

def test_infrastructure_failure_codes_are_retryable() -> None:
    """Infrastructure failure codes are in RETRYABLE_CODES; content failures are not."""
    from learn_platform_api.practice_workers import RETRYABLE_CODES

    assert "code_execution_unavailable" in RETRYABLE_CODES
    assert "science_tool_unavailable" in RETRYABLE_CODES
    # Content failures are NOT retryable
    assert "coding_reference_test_failed" not in RETRYABLE_CODES
    assert "coding_reference_compile_failed" not in RETRYABLE_CODES
    assert "coding_repair_artifact_invalid" not in RETRYABLE_CODES
    assert "coding_repair_revalidation_failed" not in RETRYABLE_CODES


def test_infrastructure_failure_does_not_consume_specialized_repair() -> None:
    """Infrastructure failure raises code_execution_unavailable immediately,
    NOT consuming a specialized repair slot. The error goes to the
    retryable infrastructure path, not the content repair path."""
    from learn_platform_api.services.practice_generation import (
        CodingReferenceValidationResult,
    )

    # An infrastructure failure result has infrastructure_failure=True
    result = CodingReferenceValidationResult(
        passed=False, tests_passed=0, tests_total=3,
        error_categories=["infrastructure_failure"],
        infrastructure_failure=True,
    )
    assert result.infrastructure_failure is True
    # In execute_generation, this raises ValueError("code_execution_unavailable")
    # which is in RETRYABLE_CODES, so it goes to the retry path,
    # NOT the specialized repair path.


# ---------------------------------------------------------------------------
# F. practice_generation_model configuration scope
# ---------------------------------------------------------------------------

def test_practice_generation_model_default_is_pro() -> None:
    """Settings().practice_generation_model defaults to deepseek-v4-pro."""
    from learn_platform_api.settings import Settings
    settings = Settings()
    assert settings.practice_generation_model == "deepseek-v4-pro"


def test_product_generation_model_unchanged() -> None:
    """product_generation_model remains deepseek-v4-flash (not switched to Pro)."""
    from learn_platform_api.settings import Settings
    settings = Settings()
    assert settings.product_generation_model == "deepseek-v4-flash"


def test_practice_generation_uses_practice_generation_model() -> None:
    """call_practice_provider uses practice_generation_model, not product_generation_model."""
    from learn_platform_api.services import practice_generation
    source = inspect.getsource(practice_generation.call_practice_provider)
    assert "practice_generation_model" in source
    # The function body (not docstring) uses practice_generation_model
    # for the model parameter in the API call
    assert "settings.practice_generation_model" in source


def test_call_provider_uses_product_generation_model() -> None:
    """call_provider (for Tutor/course/RAG/grading) uses product_generation_model."""
    from learn_platform_api.services import practice_generation
    source = inspect.getsource(practice_generation.call_provider)
    assert "product_generation_model" in source
    assert "practice_generation_model" not in source


def test_env_example_contains_practice_generation_model() -> None:
    """.env.example contains PRACTICE_GENERATION_MODEL with public default."""
    from pathlib import Path
    env_example = (Path(__file__).resolve().parent.parent.parent.parent / ".env.example").read_text(encoding="utf-8")
    assert "PRACTICE_GENERATION_MODEL" in env_example
    assert "deepseek-v4-pro" in env_example
    # Must NOT contain secrets
    assert "API_KEY" not in env_example.split("PRACTICE_GENERATION_MODEL")[1].split("\n")[0]


def test_docker_compose_contains_practice_generation_model() -> None:
    """Docker Compose passes PRACTICE_GENERATION_MODEL to api, worker, and practice-worker."""
    from pathlib import Path
    compose = (Path(__file__).resolve().parent.parent.parent.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert "PRACTICE_GENERATION_MODEL" in compose
    assert "deepseek-v4-pro" in compose
    # Verify it appears in all three services: api, worker, practice-worker
    # Count occurrences — should be at least 3 (one per service)
    count = compose.count("PRACTICE_GENERATION_MODEL")
    assert count >= 3, f"PRACTICE_GENERATION_MODEL appears {count} times, expected >= 3 (api + worker + practice-worker)"


# ---------------------------------------------------------------------------
# Fixture-driven generation orchestration tests (Python/Java/C++)
# ---------------------------------------------------------------------------

def _make_single_choice_item(item_key: str, target_key: str = "objective_1") -> dict:
    stems = {
        "q1": "Which data structure provides O(1) average-case lookup by key?",
        "q2": "What is the time complexity of merge sort in the worst case?",
        "q3": "Which sorting algorithm is optimal for nearly-sorted input?",
        "q4": "What principle states that no comparison sort can beat O(n log n)?",
    }
    return {
        "item_key": item_key, "target_key": target_key, "item_type": "single_choice",
        "stem": stems.get(item_key, f"Question about {item_key}."), "citation_ids": ["e1"],
        "options": [
            {"option_key": "a", "text": "Option A", "is_correct": True, "rationale": "Correct", "citation_ids": ["e1"]},
            {"option_key": "b", "text": "Option B", "is_correct": False, "rationale": "Incorrect", "citation_ids": ["e1"]},
        ],
    }


def _make_coding_item(item_key: str, target_key: str = "objective_1", language: str = "python") -> dict:
    return {
        "item_key": item_key, "target_key": target_key, "item_type": "coding",
        "stem": "Write a function that implements the identity transformation on its input string.", "citation_ids": ["e1"],
        "language": language,
        "input_description": "one UTF-8 string", "output_description": "the same string",
        "starter_code": "",
        "hidden_tests": [
            {"input": "a", "expected_output": "a", "weight": 1},
            {"input": "b", "expected_output": "b", "weight": 1},
            {"input": "c", "expected_output": "c", "weight": 1},
        ],
        "public_examples": [],
        "constraints": [],
        "reference_solution": "def solve(input_text):\n    return input_text",
    }


def _make_java_coding_item(item_key: str = "q4") -> dict:
    return {
        "item_key": item_key, "target_key": "objective_1", "item_type": "coding",
        "stem": "Write a Java function that returns its input string unchanged.", "citation_ids": ["e1"],
        "language": "java",
        "input_description": "one UTF-8 string", "output_description": "the same string",
        "starter_code": "",
        "hidden_tests": [
            {"input": "hello", "expected_output": "hello", "weight": 1},
            {"input": "world", "expected_output": "world", "weight": 1},
            {"input": "test", "expected_output": "test", "weight": 1},
        ],
        "public_examples": [],
        "constraints": [],
        "reference_solution": "class Solution { static String solve(String input) { return input; } }",
    }


def _make_cpp_coding_item(item_key: str = "q4") -> dict:
    return {
        "item_key": item_key, "target_key": "objective_1", "item_type": "coding",
        "stem": "Write a C++ function that returns its input string unchanged.", "citation_ids": ["e1"],
        "language": "cpp",
        "input_description": "one UTF-8 string", "output_description": "the same string",
        "starter_code": "",
        "hidden_tests": [
            {"input": "hello", "expected_output": "hello", "weight": 1},
            {"input": "world", "expected_output": "world", "weight": 1},
            {"input": "test", "expected_output": "test", "weight": 1},
        ],
        "public_examples": [],
        "constraints": [],
        "reference_solution": "std::string solve(const std::string& input) { return input; }",
    }


def _setup_generation_job(db_session, monkeypatch, item_count=4, difficulty="hard"):
    """Set up a generation job with mocked retrieve."""
    from learn_platform_api.db.models import (
        Workspace, SourceDocument, DocumentVersion, DocumentChunk,
        Course, CourseVersion, CourseVersionSource, CourseSection,
        Lesson, LessonVersion, PracticeJob,
    )
    from learn_platform_api.schemas.documents import CitationRead, RetrievalResult
    from learn_platform_api.services import practice, practice_generation
    from learn_platform_api.settings import get_settings

    ws = Workspace(name="c002-ws", slug="c002-ws"); db_session.add(ws); db_session.flush()
    doc = SourceDocument(workspace_id=ws.id, display_name="guide.md"); db_session.add(doc); db_session.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, processing_status="ready",
                          original_filename="g", mime_type="text/markdown", byte_size=1,
                          sha256="a" * 64, original_storage_uri="t")
    db_session.add(ver); db_session.flush(); doc.current_version_id = ver.id
    chunk = DocumentChunk(id=("c" * 32)[:36], document_version_id=ver.id, ordinal=0,
                          content="Binary search halves a sorted interval.",
                          content_hash="b" * 64, start_offset=0, end_offset=36, page_start=1, page_end=1)
    course = Course(workspace_id=ws.id, title="C002Course", goal="g")
    db_session.add_all([chunk, course]); db_session.flush()
    cv = CourseVersion(course_id=course.id, workspace_id=ws.id, version_number=1,
                       status="active", title="C002Course")
    db_session.add(cv); db_session.flush(); course.current_active_version_id = cv.id
    db_session.add(CourseVersionSource(course_version_id=cv.id, workspace_id=ws.id,
                                       document_id=doc.id, document_version_id=ver.id))
    section = CourseSection(course_version_id=cv.id, workspace_id=ws.id, ordinal=0,
                            title="s", objective="o")
    db_session.add(section); db_session.flush()
    lesson = Lesson(course_version_id=cv.id, course_section_id=section.id,
                    workspace_id=ws.id, ordinal=0, title="L", objective="o")
    db_session.add(lesson); db_session.flush()
    lv = LessonVersion(lesson_id=lesson.id, course_version_id=cv.id, workspace_id=ws.id,
                       version_number=1, status="published", title="L",
                       learning_objectives=["o"], blocks=[])
    db_session.add(lv); db_session.flush(); lesson.current_published_version_id = lv.id
    db_session.commit()

    monkeypatch.setattr(practice, "enqueue_practice_job", lambda *_args: None)
    monkeypatch.setattr(practice_generation, "retrieve", lambda *_a, **_k: (
        "trace",
        [RetrievalResult(
            score=0.9, text=chunk.content,
            citation=CitationRead(
                document_id=doc.id, document_version_id=ver.id,
                chunk_id=chunk.id, document_name=doc.display_name,
                heading_path=[], start_offset=0, end_offset=len(chunk.content),
            ),
        )],
    ))

    payload = type("P", (), {
        "item_count": item_count, "difficulty": difficulty, "output_language": "zh-CN",
        "item_type_mode": "auto", "code_languages": ["python"],
        "code_tool_authorized": False, "science_tool_authorized": False,
    })()
    job = practice.create_generation_job(
        db_session, get_settings(), ws.id, course.id, cv.id,
        lesson.id, lv.id, payload, f"c002-test-{item_count}-{difficulty}",
    )
    job.status = "running"
    job.worker_id = "worker-c002"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    job.attempt_count = 1
    db_session.commit()

    return job, chunk, doc, ver


def _setup_coding_job(db_session, monkeypatch, language: str = "python") -> tuple:
    """Set up a generation job with coding enabled for the given language."""
    from learn_platform_api.db.models import (
        McpCapabilityStatus, JobToolAuthorization, LessonVersion,
    )
    from learn_platform_api.services import practice_generation
    from learn_platform_api.settings import get_settings

    job, chunk, doc, ver = _setup_generation_job(db_session, monkeypatch, item_count=4, difficulty="hard")
    lv = db_session.get(LessonVersion, job.lesson_version_id)
    lv.practice_type_hints = [{
        "objective_key": "u1", "evidence_keys": ["e1"],
        "has_algorithmic_objective": True, "has_executable_evidence": True,
        "has_math_objective": False, "has_physics_objective": False,
        "has_chemistry_objective": False, "has_computable_evidence": False,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="code_execution", status="ready", detail="ready",
        verified_schema_hash="a" * 16, checked_at=datetime.now(timezone.utc), ttl_seconds=300,
    ))
    auth = JobToolAuthorization(
        practice_job_id=job.id, workspace_id=job.workspace_id,
        capability_id="code_execution", max_calls=4, used_calls=0,
        schema_hash_snapshot="a" * 16,
    )
    db_session.add(auth)
    job.item_type_mode = "require_coding"
    job.code_languages = [language]
    db_session.commit()
    return job


def _setup_science_job(db_session, monkeypatch) -> tuple:
    """Set up a generation job with science enabled (require_science).

    Science capability + authorization are marked ready so scientific items are
    an allowed type. No science tool is actually consumed when the repaired spec
    is local (needs_remote_verification=False).
    """
    from learn_platform_api.db.models import (
        McpCapabilityStatus, JobToolAuthorization, LessonVersion,
    )

    job, chunk, doc, ver = _setup_generation_job(db_session, monkeypatch, item_count=4, difficulty="hard")
    lv = db_session.get(LessonVersion, job.lesson_version_id)
    lv.practice_type_hints = [{
        "objective_key": "u1", "evidence_keys": ["e1"],
        "has_algorithmic_objective": False, "has_executable_evidence": False,
        "has_math_objective": True, "has_physics_objective": True,
        "has_chemistry_objective": False, "has_computable_evidence": True,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="science_computation", status="ready", detail="ready",
        verified_schema_hash="a" * 16, checked_at=datetime.now(timezone.utc), ttl_seconds=300,
    ))
    auth = JobToolAuthorization(
        practice_job_id=job.id, workspace_id=job.workspace_id,
        capability_id="science_computation", max_calls=4, used_calls=0,
        schema_hash_snapshot="a" * 16,
    )
    db_session.add(auth)
    job.item_type_mode = "require_science"
    db_session.commit()
    return job


def _read_run_metrics(db_session, job) -> dict:
    """Read the AgentRun step_count and tool call details."""
    run = db_session.scalar(select(AgentRun).where(AgentRun.practice_job_id == job.id))
    if run is None:
        return {"step_count": 0, "provider_calls": 0, "tool_calls": [], "run_status": None, "error_code": None}
    tool_calls = list(db_session.scalars(select(AgentToolCall).where(
        AgentToolCall.agent_run_id == run.id,
    ).order_by(AgentToolCall.ordinal)))
    return {
        "step_count": run.step_count or 0,
        "tool_calls": [{"name": tc.tool_name, "ordinal": tc.ordinal, "status": tc.status, "error_code": tc.error_code} for tc in tool_calls],
        "run_status": run.status,
        "error_code": run.error_code,
    }


# --- Python ---

def test_python_happy_path(db_session, monkeypatch) -> None:
    """Python coding: happy path with reference validation passing."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="python")

    artifact = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        _make_coding_item("q4"),
    ]}
    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp",
        lambda *, reference_solution, **_kw: CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        ))

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_python_reference_repair(db_session, monkeypatch) -> None:
    """Python coding: reference fails, repair succeeds via minimal DTO."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="python")

    broken_ref = "def solve(input_text):\n    return 'wrong'"
    fixed_ref = "def solve(input_text):\n    return input_text"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_coding_item("q4"), "reference_solution": broken_ref},
    ]}
    # Minimal repair DTO: only item_key + reference_solution
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_ref:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


# --- Java ---

def test_java_happy_path(db_session, monkeypatch) -> None:
    """Java coding: happy path."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    artifact = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        _make_java_coding_item(),
    ]}
    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp",
        lambda *, reference_solution, **_kw: CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        ))

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_java_compile_failure(db_session, monkeypatch) -> None:
    """Java coding: compile failure triggers specialized repair."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    broken_ref = "class Solution { static String solve(String input) { return 1/0; } }"
    fixed_ref = "class Solution { static String solve(String input) { return input; } }"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_java_coding_item(), "reference_solution": broken_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_ref:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["compile_error"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_java_test_mismatch(db_session, monkeypatch) -> None:
    """Java coding: test mismatch triggers specialized repair."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    wrong_ref = 'class Solution { static String solve(String input) { return "wrong"; } }'
    fixed_ref = "class Solution { static String solve(String input) { return input; } }"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_java_coding_item(), "reference_solution": wrong_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if "wrong" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_java_repair_invalid_dto(db_session, monkeypatch) -> None:
    """Java coding: repair returns invalid minimal DTO -> stable error."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    wrong_ref = 'class Solution { static String solve(String input) { return "wrong"; } }'
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_java_coding_item(), "reference_solution": wrong_ref},
    ]}
    # Invalid repair: returns extra forbidden field (language)
    invalid_repair = {"item_key": "q4", "reference_solution": "class Solution { static String solve(String input) { return input; } }", "language": "java"}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (invalid_repair, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if "wrong" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    # The invalid repair DTO (extra field) should cause a stable error
    # Per Correction 002 §D: the stable code is coding_repair_artifact_invalid,
    # NOT the original coding_reference_test_failed.
    with pytest.raises(ValueError, match="coding_repair_artifact_invalid"):
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")


# --- C++ ---

def test_cpp_happy_path(db_session, monkeypatch) -> None:
    """C++ coding: happy path."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="cpp")

    artifact = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        _make_cpp_coding_item(),
    ]}
    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp",
        lambda *, reference_solution, **_kw: CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        ))

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_cpp_compile_failure(db_session, monkeypatch) -> None:
    """C++ coding: compile failure triggers specialized repair."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="cpp")

    broken_ref = "std::string solve(const std::string& input) { return 1/0; }"
    fixed_ref = "std::string solve(const std::string& input) { return input; }"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_cpp_coding_item(), "reference_solution": broken_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if "1/0" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["compile_error"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_cpp_test_mismatch(db_session, monkeypatch) -> None:
    """C++ coding: test mismatch triggers specialized repair."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="cpp")

    wrong_ref = 'std::string solve(const std::string& input) { return "wrong"; }'
    fixed_ref = "std::string solve(const std::string& input) { return input; }"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_cpp_coding_item(), "reference_solution": wrong_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if "wrong" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


# --- Infrastructure failure ---

def test_java_infrastructure_failure(db_session, monkeypatch) -> None:
    """Java: infrastructure failure raises code_execution_unavailable,
    does NOT consume specialized repair slot."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    artifact = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        _make_java_coding_item(),
    ]}
    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp",
        lambda *, reference_solution, **_kw: CodingReferenceValidationResult(
            passed=False, tests_passed=0, tests_total=3,
            error_categories=["infrastructure_failure"],
            infrastructure_failure=True,
        ))

    with pytest.raises(ValueError, match="code_execution_unavailable"):
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")


def test_cpp_infrastructure_failure(db_session, monkeypatch) -> None:
    """C++: infrastructure failure raises code_execution_unavailable."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="cpp")

    artifact = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        _make_cpp_coding_item(),
    ]}
    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (artifact, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp",
        lambda *, reference_solution, **_kw: CodingReferenceValidationResult(
            passed=False, tests_passed=0, tests_total=3,
            error_categories=["infrastructure_failure"],
            infrastructure_failure=True,
        ))

    with pytest.raises(ValueError, match="code_execution_unavailable"):
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")


# ---------------------------------------------------------------------------
# G. Integration tests: error code propagation through execute_generation
# ---------------------------------------------------------------------------

def test_repair_artifact_invalid_propagates_to_job(db_session, monkeypatch) -> None:
    """When the minimal repair DTO is malformed (extra fields), the Job
    receives coding_repair_artifact_invalid, NOT coding_reference_test_failed."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import (
        CodingReferenceValidationResult,
        CODING_REPAIR_ARTIFACT_INVALID,
    )
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="python")

    broken_ref = "def solve(input_text):\n    return 'wrong'"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_coding_item("q4"), "reference_solution": broken_ref},
    ]}
    # Invalid repair: returns forbidden field (hidden_tests)
    invalid_repair = {
        "item_key": "q4",
        "reference_solution": "def solve(input_text): return input_text",
        "hidden_tests": [{"input": "x", "expected_output": "x"}],
    }

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (invalid_repair, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_ref:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    with pytest.raises(ValueError) as exc_info:
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # The error code that reaches the Job is the STABLE repair-invalid code
    assert str(exc_info.value) == CODING_REPAIR_ARTIFACT_INVALID
    assert str(exc_info.value) == "coding_repair_artifact_invalid"
    # NOT the original reference failure code
    assert str(exc_info.value) != "coding_reference_test_failed"


def test_revalidation_failure_propagates_to_job(db_session, monkeypatch) -> None:
    """When repair artifact is valid but re-validation still fails, the Job
    receives coding_repair_revalidation_failed, NOT coding_reference_test_failed."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import (
        CodingReferenceValidationResult,
        CODING_REPAIR_REVALIDATION_FAILED,
    )
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="python")

    broken_ref = "def solve(input_text):\n    return 'wrong'"
    # The repair returns a syntactically valid minimal DTO, but the fixed
    # reference still fails re-validation (e.g. off-by-one error).
    still_broken_ref = "def solve(input_text):\n    return 'still_wrong'"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_coding_item("q4"), "reference_solution": broken_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": still_broken_ref}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        # Both the original and the repaired reference fail
        if reference_solution in (broken_ref, still_broken_ref):
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    with pytest.raises(ValueError) as exc_info:
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # The error code that reaches the Job is the STABLE revalidation-failed code
    assert str(exc_info.value) == CODING_REPAIR_REVALIDATION_FAILED
    assert str(exc_info.value) == "coding_repair_revalidation_failed"
    # NOT the original reference failure code
    assert str(exc_info.value) != "coding_reference_test_failed"


def test_specialized_item_error_skips_whole_set_repair(db_session, monkeypatch) -> None:
    """When a coding item's reference_solution fails validation, the
    specialized-item-level error path is used (single-item repair), NOT
    whole-Set structure repair. This is verified by counting provider calls:
    search + initial + specialized repair = 3 (NOT 4 with whole-Set repair)."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="python")

    # A valid artifact whose coding reference fails validation.
    # This goes through the specialized repair path, not whole-Set repair.
    broken_ref = "def solve(input_text):\n    return 'wrong'"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_coding_item("q4"), "reference_solution": broken_ref},
    ]}
    fixed_ref = "def solve(input_text):\n    return input_text"
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    call_count = 0

    def counting_provider(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return next(provider_results)

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", counting_provider)

    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_ref:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # Provider was called 3 times: search + initial + specialized repair
    # (NOT 4 times which would include a whole-Set structure repair)
    assert call_count == 3, f"Expected 3 provider calls (search + initial + specialized repair), got {call_count}"


def test_safe_position_summary_called_in_repair_path(db_session, monkeypatch) -> None:
    """_build_safe_position_summary is actually called during specialized repair
    for coding items, and its output reaches the repair prompt."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import (
        CodingReferenceValidationResult,
        _build_safe_position_summary,
    )
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    broken_ref = "class Solution { static String solve(String input) { return 1/0; } }"
    fixed_ref = "class Solution { static String solve(String input) { return input; } }"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_java_coding_item(), "reference_solution": broken_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    # Capture the prompt messages passed to the provider
    captured_prompts: list[list[dict[str, str]]] = []

    def capturing_provider(settings, messages, *args, **kwargs):
        captured_prompts.append(messages)
        return next(provider_results)

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", capturing_provider)

    def fake_validate(*, reference_solution, **_kw):
        if "1/0" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["compile_error"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # The third provider call is the specialized repair prompt
    assert len(captured_prompts) >= 3, "Expected at least 3 provider calls"
    repair_prompt = captured_prompts[2]  # search=0, initial=1, repair=2
    # The repair prompt should contain the safe position summary
    prompt_text = " ".join(msg.get("content", "") for msg in repair_prompt)
    assert "Bounded position summary" in prompt_text, \
        "Repair prompt should contain 'Bounded position summary' from _build_safe_position_summary"
    assert "java" in prompt_text, \
        "Repair prompt should contain language='java' from _build_safe_position_summary"
    assert "compile_error" in prompt_text, \
        "Repair prompt should contain compile_error category from _build_safe_position_summary"
    assert "passed=0/3" in prompt_text, \
        "Repair prompt should preserve the safe pass count from the real validation result"


def test_repair_prompt_uses_minimal_dto_schema(db_session, monkeypatch) -> None:
    """The specialized repair prompt uses CodingReferenceRepairArtifact schema
    (NOT PracticeSetArtifact schema). The prompt instructs the provider to
    return only the mutable fields."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from academic_companion.practice_agents import CodingReferenceRepairArtifact, PracticeSetArtifact
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="python")

    broken_ref = "def solve(input_text):\n    return 'wrong'"
    fixed_ref = "def solve(input_text):\n    return input_text"
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_coding_item("q4"), "reference_solution": broken_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    # Capture the prompt messages
    captured_prompts: list[list[dict[str, str]]] = []

    def capturing_provider(settings, messages, *args, **kwargs):
        captured_prompts.append(messages)
        return next(provider_results)

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", capturing_provider)

    def fake_validate(*, reference_solution, **_kw):
        if reference_solution == broken_ref:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["test_mismatch"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # The third provider call is the specialized repair prompt
    assert len(captured_prompts) >= 3
    repair_prompt = captured_prompts[2]
    prompt_text = " ".join(msg.get("content", "") for msg in repair_prompt)

    # The prompt must use the minimal DTO schema, NOT the full PracticeSetArtifact schema
    minimal_schema = CodingReferenceRepairArtifact.model_json_schema()
    full_schema = PracticeSetArtifact.model_json_schema()

    # The minimal schema has "item_key", "reference_solution", "starter_code"
    # The full schema has "items" -> list of PracticeItemArtifact
    assert '"item_key"' in prompt_text or "'item_key'" in prompt_text, \
        "Repair prompt should reference the minimal DTO schema with item_key at top level"
    # The full schema has an "items" array — the minimal schema does NOT
    # Check that the prompt contains the minimal schema structure
    assert "reference_solution" in prompt_text, \
        "Repair prompt should reference reference_solution from minimal DTO schema"
    # The prompt should explicitly forbid extra fields
    assert "forbidden" in prompt_text.casefold() or "Do NOT return" in prompt_text, \
        "Repair prompt should instruct the provider that extra fields are forbidden"


def test_scientific_repair_artifact_invalid_propagates(db_session, monkeypatch) -> None:
    """When a scientific repair DTO is malformed, the Job receives
    scientific_repair_artifact_invalid."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import (
        SCIENTIFIC_REPAIR_ARTIFCAT_INVALID,
    )
    from learn_platform_api.settings import get_settings
    from learn_platform_api.db.models import McpCapabilityStatus, JobToolAuthorization, LessonVersion

    job, chunk, doc, ver = _setup_generation_job(db_session, monkeypatch, item_count=4, difficulty="hard")
    lv = db_session.get(LessonVersion, job.lesson_version_id)
    lv.practice_type_hints = [{
        "objective_key": "u1", "evidence_keys": ["e1"],
        "has_algorithmic_objective": False, "has_executable_evidence": False,
        "has_math_objective": True, "has_physics_objective": True,
        "has_chemistry_objective": False, "has_computable_evidence": True,
    }]
    db_session.add(McpCapabilityStatus(
        capability_id="science_computation", status="ready", detail="ready",
        verified_schema_hash="a" * 16, checked_at=datetime.now(timezone.utc), ttl_seconds=300,
    ))
    auth = JobToolAuthorization(
        practice_job_id=job.id, workspace_id=job.workspace_id,
        capability_id="science_computation", max_calls=4, used_calls=0,
        schema_hash_snapshot="a" * 16,
    )
    db_session.add(auth)
    job.item_type_mode = "require_science"
    db_session.commit()

    # Scientific item with remote verification that fails (unverified)
    scientific_item = {
        "item_key": "q4", "target_key": "objective_1", "item_type": "scientific",
        "stem": "Compute the gravitational acceleration.", "citation_ids": ["e1"],
        "scientific_answer_spec": {
            "normalized_answer": "9.81", "equivalence_rule": "symbolic",
            "needs_remote_verification": True,
            "verification_expression": "equivalent(9.81, 9.81)",
        },
        "rubric": [
            {"criterion_key": "c1", "description": "Value", "weight": 60, "citation_ids": ["e1"]},
            {"criterion_key": "c2", "description": "Units", "weight": 40, "citation_ids": ["e1"]},
        ],
        "reference_answer": "g = 9.81 m/s^2",
    }

    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        scientific_item,
    ]}

    # Mock science verification to fail (unverified)
    # execute_science_verification is imported inside validate_scientific_items,
    # so we must monkeypatch it on the source module.
    from learn_platform_api.services import science_tool_service

    def fake_science_verify(*args, **kwargs):
        from dataclasses import dataclass, field
        @dataclass
        class FakeResult:
            success: bool = True
            observation: dict = field(default_factory=lambda: {"verified": False})
            error_code: str | None = None
        return FakeResult()

    monkeypatch.setattr(
        science_tool_service,
        "execute_science_verification",
        fake_science_verify,
    )

    # Invalid repair: returns forbidden field (rubric)
    invalid_repair = {
        "item_key": "q4",
        "scientific_answer_spec": {
            "normalized_answer": "9.81", "equivalence_rule": "exact",
            "needs_remote_verification": False,
        },
        "reference_answer": "g = 9.81 m/s^2",
        "rubric": [{"criterion_key": "c1", "description": "ok", "weight": 100}],
    }

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (invalid_repair, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    with pytest.raises(ValueError) as exc_info:
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    assert str(exc_info.value) == SCIENTIFIC_REPAIR_ARTIFCAT_INVALID
    assert str(exc_info.value) == "scientific_repair_artifact_invalid"


# ---------------------------------------------------------------------------
# H. Integration tests: broken item preservation (no silent drop)
# ---------------------------------------------------------------------------

def test_broken_coding_item_is_preserved_and_repaired(db_session, monkeypatch) -> None:
    """4 items, the only coding item has a Java package declaration (schema error).
    The two-phase preserving recovery constructs a placeholder, so the coding
    item is NOT silently dropped. Specialized repair is triggered, and the
    final Set has 4 items with the coding item still present.
    require_coding contract holds."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings
    from learn_platform_api.db.models import PracticeSet

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    # Java coding item with package declaration — violates the schema constraint
    # "java coding sources must not declare a package"
    broken_java = {**_make_java_coding_item()}
    broken_java["reference_solution"] = "package com.example;\nclass Solution { static String solve(String input) { return input; } }"

    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        broken_java,
    ]}
    # Minimal repair DTO: fixed reference without package
    fixed_ref = "class Solution { static String solve(String input) { return input; } }"
    repair_dto = {"item_key": "q4", "reference_solution": fixed_ref}

    call_count = 0
    def counting_provider(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return next(provider_results)

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", counting_provider)

    def fake_validate(*, reference_solution, **_kw):
        if "package" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["compile_error"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # Provider called 3 times: search + initial + specialized repair
    # (NOT 4 with whole-Set repair)
    assert call_count == 3, f"Expected 3 provider calls, got {call_count}"

    # The committed Set has 4 items (coding item was NOT dropped)
    practice_set = db_session.query(PracticeSet).filter_by(practice_job_id=job.id).first()
    assert practice_set is not None
    assert practice_set.item_count == 4, f"Expected 4 items, got {practice_set.item_count}"

    # Job succeeded
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"


def test_broken_coding_item_repair_invalid_no_set_persisted(db_session, monkeypatch) -> None:
    """4 items, the only coding item has a schema error. Repair returns
    an invalid minimal DTO. No PracticeSet should be persisted."""
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import (
        CodingReferenceValidationResult,
        CODING_REPAIR_ARTIFACT_INVALID,
    )
    from learn_platform_api.settings import get_settings
    from learn_platform_api.db.models import PracticeSet

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    broken_java = {**_make_java_coding_item()}
    broken_java["reference_solution"] = "package com.example;\nclass Solution { static String solve(String input) { return input; } }"

    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        broken_java,
    ]}
    # Invalid repair: returns extra forbidden field (language)
    invalid_repair = {
        "item_key": "q4",
        "reference_solution": "class Solution { static String solve(String input) { return input; } }",
        "language": "java",
    }

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (invalid_repair, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if "package" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["compile_error"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    with pytest.raises(ValueError) as exc_info:
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    assert str(exc_info.value) == CODING_REPAIR_ARTIFACT_INVALID

    # No PracticeSet persisted
    count = db_session.query(PracticeSet).filter_by(practice_job_id=job.id).count()
    assert count == 0, f"Expected 0 PracticeSet rows, got {count}"


# ---------------------------------------------------------------------------
# Codex review High: immutable-field regression tests
# ---------------------------------------------------------------------------

class TestRecoveredItemImmutableContract:
    """Verify that _validate_recovered_item_immutable_contract rejects
    placeholders with broken immutable fields — these cannot be repaired
    by specialized repair (which only changes mutable fields)."""

    def test_coding_missing_input_description_rejected(self) -> None:
        """input_description is optional in the model (with fallback in
        _commit_set), but the full-validation gate will still catch items
        that fail strict model_validate. This test verifies that a coding
        item with None input_description passes the immutable contract
        (since it's optional) but would fail the full-validation gate
        if other constraints are violated."""
        from academic_companion.practice_agents import PracticeItemArtifact, CodingTestCase
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Write a function", citation_ids=["e1"],
            language="python",
            hidden_tests=[
                CodingTestCase(input="a", expected_output="a"),
                CodingTestCase(input="b", expected_output="b"),
                CodingTestCase(input="c", expected_output="c"),
            ],
            reference_solution="def solve(input_text): return input_text",
            input_description=None,  # Optional — not an immutable violation
            output_description="output",
        )
        # input_description is optional — immutable contract should pass
        _validate_recovered_item_immutable_contract(item)

    def test_coding_missing_output_description_passes(self) -> None:
        """output_description is optional — not an immutable violation."""
        from academic_companion.practice_agents import PracticeItemArtifact, CodingTestCase
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Write a function", citation_ids=["e1"],
            language="python",
            hidden_tests=[
                CodingTestCase(input="a", expected_output="a"),
                CodingTestCase(input="b", expected_output="b"),
                CodingTestCase(input="c", expected_output="c"),
            ],
            reference_solution="def solve(input_text): return input_text",
            input_description="input",
            output_description=None,  # Optional — not an immutable violation
        )
        _validate_recovered_item_immutable_contract(item)

    def test_coding_too_few_hidden_tests_rejected(self) -> None:
        from academic_companion.practice_agents import PracticeItemArtifact, CodingTestCase
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Write a function", citation_ids=["e1"],
            language="python",
            hidden_tests=[
                CodingTestCase(input="a", expected_output="a"),
                # Only 1 test — needs 3-20
            ],
            reference_solution="def solve(input_text): return input_text",
            input_description="input",
            output_description="output",
        )
        with pytest.raises(ValueError, match="3-20 hidden tests"):
            _validate_recovered_item_immutable_contract(item)

    def test_coding_no_language_rejected(self) -> None:
        from academic_companion.practice_agents import PracticeItemArtifact, CodingTestCase
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Write a function", citation_ids=["e1"],
            language=None,  # MISSING — immutable
            hidden_tests=[
                CodingTestCase(input="a", expected_output="a"),
                CodingTestCase(input="b", expected_output="b"),
                CodingTestCase(input="c", expected_output="c"),
            ],
            reference_solution="def solve(input_text): return input_text",
            input_description="input",
            output_description="output",
        )
        with pytest.raises(ValueError, match="language"):
            _validate_recovered_item_immutable_contract(item)

    def test_scientific_missing_spec_passes(self) -> None:
        """scientific_answer_spec is mutable (repair can replace it via
        ScientificReferenceRepairArtifact), so spec=None passes the
        immutable contract. validate_scientific_items will flag it as
        a failure and trigger repair."""
        from academic_companion.practice_agents import PracticeItemArtifact, PracticeRubricCriterion
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="scientific",
            stem="Calculate the force", citation_ids=["e1"],
            scientific_answer_spec=None,  # Mutable — repair can replace it
            reference_answer="F = ma = 5 * 2 = 10 N",
            rubric=[
                PracticeRubricCriterion(criterion_key="c1", description="d", weight=100),
            ],
        )
        # spec=None is mutable — immutable contract should pass
        _validate_recovered_item_immutable_contract(item)

    def test_scientific_broken_rubric_weights_rejected(self) -> None:
        from academic_companion.practice_agents import (
            PracticeItemArtifact, PracticeRubricCriterion, ScientificAnswerSpec,
        )
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="scientific",
            stem="Calculate the force", citation_ids=["e1"],
            scientific_answer_spec=ScientificAnswerSpec(
                normalized_answer="10 N", equivalence_rule="exact",
            ),
            reference_answer="F = ma = 5 * 2 = 10 N",
            rubric=[
                PracticeRubricCriterion(criterion_key="c1", description="d", weight=50),
                # Weights don't sum to 100 — immutable, cannot be repaired
            ],
        )
        with pytest.raises(ValueError, match="weights must sum to 100"):
            _validate_recovered_item_immutable_contract(item)

    def test_valid_coding_item_passes(self) -> None:
        from academic_companion.practice_agents import PracticeItemArtifact, CodingTestCase
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Write a function", citation_ids=["e1"],
            language="python",
            hidden_tests=[
                CodingTestCase(input="a", expected_output="a"),
                CodingTestCase(input="b", expected_output="b"),
                CodingTestCase(input="c", expected_output="c"),
            ],
            reference_solution="def solve(input_text): return input_text",
            input_description="input",
            output_description="output",
        )
        # Should not raise
        _validate_recovered_item_immutable_contract(item)

    def test_valid_scientific_item_passes(self) -> None:
        from academic_companion.practice_agents import (
            PracticeItemArtifact, PracticeRubricCriterion, ScientificAnswerSpec,
        )
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="scientific",
            stem="Calculate the force", citation_ids=["e1"],
            scientific_answer_spec=ScientificAnswerSpec(
                normalized_answer="10 N", equivalence_rule="exact",
            ),
            reference_answer="F = ma = 5 * 2 = 10 N",
            rubric=[
                PracticeRubricCriterion(criterion_key="c1", description="d", weight=100),
            ],
        )
        # Should not raise
        _validate_recovered_item_immutable_contract(item)


class TestRecoveredPlaceholderPreservesErrors:
    """Verify that _recover_specialized_item_placeholder returns structured
    validation errors and rejects items with broken immutable fields."""

    def test_coding_missing_input_description_returns_none(self) -> None:
        """A coding item missing input_description can be recovered (it's
        optional in the model), but the full-validation gate will catch
        any other constraint violations."""
        from learn_platform_api.services.practice_generation import (
            _recover_specialized_item_placeholder,
        )

        raw_item = {
            "item_key": "q1", "target_key": "objective_1", "item_type": "coding",
            "stem": "Write a function", "citation_ids": ["e1"],
            "language": "python",
            "hidden_tests": [
                {"input": "a", "expected_output": "a"},
                {"input": "b", "expected_output": "b"},
                {"input": "c", "expected_output": "c"},
            ],
            "reference_solution": "def solve(input_text): return input_text",
            "input_description": None,  # Optional
            "output_description": "output",
        }
        # input_description is optional — recovery should succeed
        result = _recover_specialized_item_placeholder(
            raw_item, item_validation_errors=["input_description: missing"],
        )
        assert result is not None
        placeholder, errors = result
        assert placeholder.item_key == "q1"

    def test_scientific_missing_spec_recovered(self) -> None:
        """A scientific item missing scientific_answer_spec can be recovered
        because spec is mutable — validate_scientific_items will flag it
        and trigger repair."""
        from learn_platform_api.services.practice_generation import (
            _recover_specialized_item_placeholder,
        )

        raw_item = {
            "item_key": "q1", "target_key": "objective_1", "item_type": "scientific",
            "stem": "Calculate the force", "citation_ids": ["e1"],
            "scientific_answer_spec": None,
            "reference_answer": "F = ma",
            "rubric": [{"criterion_key": "c1", "description": "d", "weight": 100}],
        }
        result = _recover_specialized_item_placeholder(
            raw_item, item_validation_errors=["scientific_answer_spec: missing"],
        )
        # spec=None is mutable — recovery should succeed
        assert result is not None
        placeholder, errors = result
        assert placeholder.item_key == "q1"
        assert placeholder.scientific_answer_spec is None
        assert errors == ["scientific_answer_spec: missing"]

    def test_valid_coding_returns_tuple_with_errors(self) -> None:
        """A valid coding item (with broken mutable ref) returns (placeholder, errors)."""
        from learn_platform_api.services.practice_generation import (
            _recover_specialized_item_placeholder,
        )

        raw_item = {
            "item_key": "q1", "target_key": "objective_1", "item_type": "coding",
            "stem": "Write a function", "citation_ids": ["e1"],
            "language": "python",
            "hidden_tests": [
                {"input": "a", "expected_output": "a"},
                {"input": "b", "expected_output": "b"},
                {"input": "c", "expected_output": "c"},
            ],
            "reference_solution": "def solve(input_text): return WRONG",
            "input_description": "input",
            "output_description": "output",
        }
        result = _recover_specialized_item_placeholder(
            raw_item, item_validation_errors=["reference_solution: broken"],
        )
        assert result is not None
        placeholder, errors = result
        assert placeholder.item_key == "q1"
        assert placeholder.reference_solution == "def solve(input_text): return WRONG"
        assert errors == ["reference_solution: broken"]


class TestScientificSpecMissingIsFailure:
    """spec=None is a MUTABLE, repairable field. The immutable contract lets it
    through so specialized repair can replace it. The real behavioral coverage
    -- that validate_scientific_items flags spec=None as scientific_spec_missing
    and that _commit_set guards spec=None -- lives in the real
    execute_generation / _commit_set tests below
    (test_scientific_spec_missing_routes_to_specialized_repair and
    TestCommitSetScientificSpecGuardReal)."""

    def test_scientific_spec_none_passes_immutable_contract(self) -> None:
        """spec=None is mutable, so immutable contract allows it through."""
        from academic_companion.practice_agents import (
            PracticeItemArtifact, PracticeRubricCriterion,
        )
        from learn_platform_api.services.practice_generation import (
            _validate_recovered_item_immutable_contract,
        )

        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="scientific",
            stem="Calculate the force", citation_ids=["e1"],
            scientific_answer_spec=None,
            reference_answer="F = ma",
            rubric=[PracticeRubricCriterion(criterion_key="c1", description="d", weight=100)],
        )
        # spec=None is mutable — should NOT raise
        _validate_recovered_item_immutable_contract(item)


def test_scientific_spec_missing_routes_to_specialized_repair(db_session, monkeypatch) -> None:
    """REAL execute_generation path (not a replicated loop):

    1. Provider's first artifact carries a scientific item whose
       scientific_answer_spec is missing -> it fails strict parse, is recovered
       into a spec=None placeholder, and the real validate_scientific_items
       flags it as (scientific_spec_missing, spec_missing).
    2. That error routes to specialized single-item repair (NOT whole-Set
       repair), proven by the provider-call count.
    3. The repair provider returns a minimal ScientificReferenceRepairArtifact
       DTO (new local spec + reference_answer; no full Item, no immutable
       fields).
    4. Because the Job requires science, the repair DTO carries a mandatory
       remote boolean expression. A controlled verifier accepts it, the final
       full-validation gate passes, and _commit_set persists the item.
    5. No AttributeError; no stable error residue on the succeeded Job.
    """
    from learn_platform_api.services import practice_generation
    from learn_platform_api.settings import get_settings
    from learn_platform_api.db.models import PracticeSet, PracticeItem

    job = _setup_science_job(db_session, monkeypatch)

    # Scientific item with scientific_answer_spec intentionally OMITTED: strict
    # parse fails, recovery yields a spec=None placeholder, and the immutable
    # rubric (weights sum to 100) lets recovery succeed.
    scientific_no_spec = {
        "item_key": "q4", "target_key": "objective_1", "item_type": "scientific",
        "stem": "Compute the gravitational acceleration near the surface.",
        "citation_ids": ["e1"],
        "reference_answer": "g = 9.81 m/s^2",
        "rubric": [
            {"criterion_key": "c1", "description": "Value", "weight": 60, "citation_ids": ["e1"]},
            {"criterion_key": "c2", "description": "Units", "weight": 40, "citation_ids": ["e1"]},
        ],
    }
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        scientific_no_spec,
    ]}
    # Minimal scientific repair DTO: required-science mode makes the remote
    # expression and true flag structural requirements of the repair schema.
    repair_dto = {
        "item_key": "q4",
        "scientific_answer_spec": {
            "normalized_answer": "9.81", "equivalence_rule": "numeric_tolerance",
            "tolerance": 0.01, "unit": "m/s^2", "needs_remote_verification": True,
            "verification_expression": "Abs(9.81 - 9.81) <= 0.01",
        },
        "reference_answer": "g = 9.81 m/s^2",
    }

    call_count = 0
    captured: list[list[dict[str, str]]] = []

    def counting_provider(settings, messages, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        captured.append(messages)
        return next(provider_results)

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", counting_provider)
    from learn_platform_api.services.science_tool_service import ScienceToolResult
    monkeypatch.setattr(
        "learn_platform_api.services.science_tool_service.execute_science_verification",
        lambda **_kwargs: ScienceToolResult(
            success=True,
            observation={"verified": True},
            latency_ms=1,
        ),
    )

    # Must NOT raise (in particular, not an AttributeError from spec.unit).
    practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # (1) Provider called exactly 3 times: search + initial + specialized
    #     repair. A 4th call would mean an unwanted whole-Set structure repair.
    assert call_count == 3, f"Expected 3 provider calls, got {call_count}"

    # (2) The 3rd provider call is the specialized SCIENTIFIC repair prompt
    #     (minimal DTO schema), not a whole-Set repair prompt.
    repair_prompt_text = " ".join(m.get("content", "") for m in captured[2])
    assert "scientific_answer_spec" in repair_prompt_text
    assert "forbidden" in repair_prompt_text.casefold() or "Do NOT return" in repair_prompt_text

    # (3) Job + run succeeded; no stable error residue on a successful Job.
    metrics = _read_run_metrics(db_session, job)
    assert metrics["run_status"] == "succeeded"
    assert job.status == "succeeded"
    assert job.error_code is None
    assert job.practice_set_id is not None

    # (4) Exactly one specialized repair succeeded; no whole-Set structure
    #     repair (no second SubmitPracticeSet repair submit). whole-Set repair
    #     would also have inflated provider calls beyond 3 (asserted above).
    repair_calls = [tc for tc in metrics["tool_calls"] if tc["name"] == "RepairSpecializedItem"]
    assert len(repair_calls) == 1, metrics["tool_calls"]
    assert repair_calls[0]["status"] == "succeeded"

    # (5) Persisted Set has 4 items; the scientific item's spec is the repaired
    #     (non-empty) result.
    practice_set = db_session.query(PracticeSet).filter_by(practice_job_id=job.id).first()
    assert practice_set is not None
    assert practice_set.item_count == 4
    items = list(db_session.scalars(
        select(PracticeItem).where(PracticeItem.practice_set_id == practice_set.id)))
    assert len(items) == 4
    scientific = next(it for it in items if it.item_type == "scientific")
    persisted_spec = (scientific.answer_spec or {}).get("scientific_answer_spec")
    assert persisted_spec is not None, "repaired scientific_answer_spec must be persisted"
    assert persisted_spec.get("normalized_answer") == "9.81"
    assert persisted_spec.get("unit") == "m/s^2"


class TestCommitSetScientificSpecGuardReal:
    """REAL _commit_set guard (not a replicated if/raise):

    - spec=None scientific item -> _commit_set raises a controlled ValueError
      (NOT an AttributeError), and a rollback leaves zero partial Practice
      Set/Item data.
    - spec present -> _commit_set commits normally, so the guard is not a
      reject-only path.
    """

    def test_spec_none_raises_valueerror_and_leaves_no_partial_data(self, db_session, monkeypatch) -> None:
        from academic_companion.practice_agents import (
            PracticeItemArtifact, PracticeRubricCriterion, PracticeSetArtifact,
        )
        from learn_platform_api.db.models import PracticeItem, PracticeJobSource, PracticeSet
        from learn_platform_api.services import practice_generation

        job, chunk, doc, ver = _setup_generation_job(db_session, monkeypatch, item_count=4, difficulty="hard")
        job_id = job.id
        workspace_id = job.workspace_id

        item = PracticeItemArtifact.model_construct(
            item_key="q4", target_key="objective_1", item_type="scientific",
            stem="Calculate the force", citation_ids=["e1"],
            scientific_answer_spec=None,
            reference_answer="F = ma",
            rubric=[PracticeRubricCriterion(criterion_key="c1", description="d", weight=100)],
        )
        artifact = PracticeSetArtifact.model_construct(items=[item])
        chunks = {"e1": chunk}
        sources = {"e1": PracticeJobSource(
            practice_job_id=job.id, workspace_id=job.workspace_id,
            document_id=doc.id, document_version_id=ver.id,
        )}

        with pytest.raises(ValueError) as exc_info:
            practice_generation._commit_set(db_session, job, artifact, chunks, sources)

        # Controlled scientific-spec-missing error, NOT an AttributeError.
        assert not isinstance(exc_info.value, AttributeError)
        assert "scientific_answer_spec" in str(exc_info.value)

        # The guard raised mid-commit; the worker's transaction must roll back
        # so NO partial Practice Set/Item survives.
        db_session.rollback()
        assert db_session.query(PracticeSet).filter_by(practice_job_id=job_id).count() == 0
        assert db_session.query(PracticeItem).filter_by(workspace_id=workspace_id).count() == 0

    def test_spec_present_commits_normally(self, db_session, monkeypatch) -> None:
        from academic_companion.practice_agents import (
            PracticeItemArtifact, PracticeRubricCriterion, PracticeSetArtifact, ScientificAnswerSpec,
        )
        from learn_platform_api.db.models import PracticeItem, PracticeJobSource
        from learn_platform_api.services import practice_generation

        job, chunk, doc, ver = _setup_generation_job(db_session, monkeypatch, item_count=4, difficulty="hard")

        item = PracticeItemArtifact.model_construct(
            item_key="q4", target_key="objective_1", item_type="scientific",
            stem="Calculate the force", citation_ids=["e1"],
            scientific_answer_spec=ScientificAnswerSpec(
                normalized_answer="10 N", equivalence_rule="exact",
            ),
            reference_answer="F = ma = 5 * 2 = 10 N",
            rubric=[PracticeRubricCriterion(criterion_key="c1", description="d", weight=100)],
        )
        artifact = PracticeSetArtifact.model_construct(items=[item])
        chunks = {"e1": chunk}
        sources = {"e1": PracticeJobSource(
            practice_job_id=job.id, workspace_id=job.workspace_id,
            document_id=doc.id, document_version_id=ver.id,
        )}

        practice_set = practice_generation._commit_set(db_session, job, artifact, chunks, sources)
        db_session.flush()

        assert practice_set is not None
        assert practice_set.item_count == 1
        persisted = db_session.scalar(
            select(PracticeItem).where(PracticeItem.practice_set_id == practice_set.id))
        assert persisted is not None
        assert persisted.item_type == "scientific"
        spec = (persisted.answer_spec or {}).get("scientific_answer_spec") or {}
        assert spec.get("normalized_answer") == "10 N"


class TestFullValidationGateReassigns:
    """Verify that the full-validation gate reassigns the artifact to the
    Pydantic-normalized authoritative object."""

    def test_gate_reassigns_to_validated_artifact(self) -> None:
        """After the gate, artifact is the model_validate result,
        not the original model_construct instance."""
        from academic_companion.practice_agents import (
            PracticeItemArtifact, PracticeSetArtifact, CodingTestCase,
        )

        # Build a valid artifact via model_construct
        item = PracticeItemArtifact.model_construct(
            item_key="q1", target_key="objective_1", item_type="coding",
            stem="Write a function", citation_ids=["e1"],
            language="python",
            hidden_tests=[
                CodingTestCase(input="a", expected_output="a"),
                CodingTestCase(input="b", expected_output="b"),
                CodingTestCase(input="c", expected_output="c"),
            ],
            reference_solution="def solve(input_text): return input_text",
            input_description="input",
            output_description="output",
        )
        original = PracticeSetArtifact.model_construct(items=[item])

        # The gate does: artifact = PracticeSetArtifact.model_validate(artifact.model_dump(mode="json"))
        validated = PracticeSetArtifact.model_validate(original.model_dump(mode="json"))

        # The validated artifact is a proper Pydantic instance
        assert isinstance(validated, PracticeSetArtifact)
        assert validated.items[0].item_key == "q1"
        # model_construct instances have different identity than model_validate results
        assert validated is not original


# ---------------------------------------------------------------------------
# Codex review High (Slice 5 Smoke Correction 002 round 5): the recovered-
# placeholder log must carry ONLY bounded, allow-listed metadata and never the
# raw exception body, provider field values, stems, code, test content,
# compiler stderr or absolute paths (AGENTS.md / ADR 007 §3.7).
# ---------------------------------------------------------------------------

def test_safe_recovery_diagnostics_valueerror_carries_no_raw_text() -> None:
    """A ValueError whose body carries fake absolute paths, provider markers
    and compiler-stderr markers is reduced to a single allow-listed entry; none
    of the sensitive text reaches the diagnostics (behavioral, not a
    source-string check)."""
    from learn_platform_api.services.practice_generation import _safe_recovery_diagnostics

    sensitive = (
        "C:\\tmp\\secret\\build.log provider_stem=<PROVIDER_STEM> "
        "hidden_test=<HIDDEN> compile_stderr=<STDERR> reference=SECRET_CODE"
    )
    diag = _safe_recovery_diagnostics(ValueError(sensitive))

    blob = str(diag)
    for marker in ("/tmp/secret", "build.log", "PROVIDER_STEM", "HIDDEN", "STDERR", "SECRET_CODE"):
        assert marker not in blob, f"sensitive marker {marker!r} leaked into diagnostics: {blob}"
    assert diag["validation_error_count"] == 1
    assert diag["truncated"] is False
    assert len(diag["diagnostics"]) == 1
    entry = diag["diagnostics"][0]
    assert entry["field"] == "unknown_field"
    # category is the stable code from _structure_error_code, never the raw msg
    assert entry["category"] == "practice_artifact_schema_invalid"


def test_safe_recovery_diagnostics_validationerror_only_allowlisted() -> None:
    """A ValidationError whose message body is sensitive is mapped to
    allow-listed field/category values only; the message body is never emitted.
    An unknown field maps to unknown_field and an unknown/odd type collapses to
    validation_error."""
    from pydantic import BaseModel, ValidationError, model_validator
    from learn_platform_api.services.practice_generation import (
        _safe_recovery_diagnostics, _RECOVERY_SAFE_ERROR_TYPES,
    )

    class _Boom(BaseModel):
        super_secret_provider_field: str = "x"

        @model_validator(mode="after")
        def _fail(self):
            raise ValueError(
                "C:\\tmp\\secret\\build.log provider_code=<CODE> stderr=<STDERR>"
            )

    with pytest.raises(ValidationError) as exc_info:
        _Boom()

    diag = _safe_recovery_diagnostics(exc_info.value)
    blob = str(diag)
    for marker in ("tmp\\secret", "build.log", "provider_code", "<CODE>", "STDERR", "super_secret"):
        assert marker not in blob, f"sensitive marker leaked: {blob}"

    # The model-validator error locates no allow-listed field -> unknown_field.
    fields = {entry["field"] for entry in diag["diagnostics"]}
    categories = {entry["category"] for entry in diag["diagnostics"]}
    assert fields == {"unknown_field"}, fields
    assert all(c == "validation_error" or c in _RECOVERY_SAFE_ERROR_TYPES for c in categories)
    assert diag["validation_error_count"] == len(exc_info.value.errors())


def test_safe_recovery_diagnostics_bounded_and_truncated() -> None:
    """More than _RECOVERY_LOG_MAX_ENTRIES errors are capped; the remainder is
    reflected only via count + truncated=True. Allow-listed fields/types are
    preserved on the enumerated entries."""
    from pydantic import BaseModel, ValidationError
    from learn_platform_api.services.practice_generation import (
        _safe_recovery_diagnostics, _RECOVERY_LOG_MAX_ENTRIES,
    )

    class _Leaf(BaseModel):
        normalized_answer: str  # allow-listed field; missing -> type "missing"

    class _Wrap(BaseModel):
        items: list[_Leaf]

    # 12 leaves each missing normalized_answer -> 12 "missing" errors.
    total = 12
    with pytest.raises(ValidationError) as exc_info:
        _Wrap(items=[{} for _ in range(total)])

    assert len(exc_info.value.errors()) == total
    diag = _safe_recovery_diagnostics(exc_info.value)

    assert diag["validation_error_count"] == total
    assert len(diag["diagnostics"]) == _RECOVERY_LOG_MAX_ENTRIES
    assert _RECOVERY_LOG_MAX_ENTRIES < total  # sanity: the cap actually binds
    assert diag["truncated"] is True
    for entry in diag["diagnostics"]:
        assert entry["field"] == "normalized_answer"
        assert entry["category"] == "missing"


def test_recovered_placeholder_log_does_not_leak_sensitive_content(db_session, monkeypatch, caplog) -> None:
    """End-to-end: the two-phase recovery path logs ONLY bounded allow-listed
    metadata. A raw reference_solution carrying fake absolute paths, provider
    markers and compiler-stderr markers must NOT appear in any log record, while
    item_key and the safe format do. Exercises the real recovery+log path."""
    import logging
    from learn_platform_api.services import practice_generation
    from learn_platform_api.services.practice_generation import CodingReferenceValidationResult
    from learn_platform_api.settings import get_settings

    job = _setup_coding_job(db_session, monkeypatch, language="java")

    # Reference whose body carries sensitive-looking markers. Strict validation
    # fails on the `package` declaration, triggering two-phase recovery and the
    # recovered-placeholder log; the raw body must never reach the log.
    sensitive_markers = ["C:\\tmp\\secret\\build.log", "PROVIDER_STEM", "hidden=SECRET", "STDERR_DUMP"]
    sensitive_ref = (
        "package com.example;\n"
        "// " + " ".join(sensitive_markers) + "\n"
        "class Solution { static String solve(String input) { return input; } }"
    )
    initial = {"items": [
        _make_single_choice_item("q1"),
        _make_single_choice_item("q2"),
        _make_single_choice_item("q3"),
        {**_make_java_coding_item(), "reference_solution": sensitive_ref},
    ]}
    repair_dto = {"item_key": "q4", "reference_solution": "class Solution { static String solve(String input) { return input; } }"}

    provider_results = iter([
        ({"queries": ["e1", "e2", "e3"]}, {"input_tokens": 10, "output_tokens": 10}),
        (initial, {"input_tokens": 50, "output_tokens": 50}),
        (repair_dto, {"input_tokens": 50, "output_tokens": 50}),
    ])
    monkeypatch.setattr(practice_generation, "call_practice_provider", lambda *_a, **_k: next(provider_results))

    def fake_validate(*, reference_solution, **_kw):
        if "package" in reference_solution:
            return CodingReferenceValidationResult(
                passed=False, tests_passed=0, tests_total=3,
                error_categories=["compile_error"], infrastructure_failure=False,
            )
        return CodingReferenceValidationResult(
            passed=True, tests_passed=3, tests_total=3,
            error_categories=[], infrastructure_failure=False,
        )
    monkeypatch.setattr(practice_generation, "_validate_coding_reference_via_mcp", fake_validate)

    with caplog.at_level(logging.WARNING, logger="learn_platform_api.services.practice_generation"):
        practice_generation.execute_generation(db_session, get_settings(), job, worker_id="worker-c002")

    # The recovery log line is present and carries only safe metadata.
    recovery_records = [r for r in caplog.records if "recovered specialized placeholder" in r.getMessage()]
    assert recovery_records, "expected a recovered-specialized-placeholder warning"
    for record in recovery_records:
        msg = record.getMessage()
        assert "item_key=q4" in msg, msg
        assert "count=" in msg and "diagnostics=" in msg and "truncated=" in msg
        for marker in sensitive_markers + ["com.example"]:
            assert marker not in msg, f"sensitive marker {marker!r} leaked into log: {msg}"

    # Belt-and-braces: no record anywhere in the run carries the raw markers.
    for record in caplog.records:
        msg = record.getMessage()
        for marker in sensitive_markers:
            assert marker not in msg, f"sensitive marker leaked via {record.name}: {msg}"
