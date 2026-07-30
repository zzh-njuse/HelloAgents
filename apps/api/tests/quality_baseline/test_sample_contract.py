"""Sample-registry contract tests (packet §5). Pure data — no Postgres."""

from __future__ import annotations

import pytest

from quality_baseline import samples
from quality_baseline.report import FORBIDDEN_FIELD_NAMES
from learn_platform_api.services.practice_type_adaptation import (
    LessonLearningProfile, SuitabilityStatus, determine_suitability, validate_item_type_mode,
)
from learn_platform_api.services.practice_type_adaptation import ItemTypeMode


def _profile(sample):
    p = sample.profile
    return LessonLearningProfile(
        objective_keys=["objective_1"], evidence_keys=["e1"],
        has_algorithmic_objective=p.get("algorithmic", False),
        has_executable_evidence=p.get("executable", False),
        has_math_objective=p.get("math", False),
        has_physics_objective=p.get("physics", False),
        has_chemistry_objective=p.get("chemistry", False),
        has_computable_evidence=p.get("computable", False),
    )


def test_registry_ids_are_unique_and_stable():
    ids = [s.sample_id for s in samples.REGISTRY.values()]
    assert len(ids) == len(set(ids))
    # Stable IDs are kebab/snake stable strings (no spaces, no dynamic content).
    for sid in ids:
        assert isinstance(sid, str) and sid == sid.strip()
        assert " " not in sid


@pytest.mark.parametrize("capability,minimum", [
    (samples.PRACTICE_CODING, 2),
    (samples.PRACTICE_SCIENCE, 2),
    (samples.NEGATIVE_CONTROL, 1),
])
def test_minimum_positive_and_negative_samples_exist(capability, minimum):
    assert len(samples.samples_for(capability)) >= minimum


def test_tutor_code_and_science_have_required_and_forbidden_each():
    for cap in (samples.TUTOR_CODE, samples.TUTOR_SCIENCE):
        caps = samples.samples_for(cap)
        assert any(s.tool_expectation == samples.REQUIRED for s in caps), cap
        assert any(s.tool_expectation == samples.FORBIDDEN for s in caps), cap


def test_required_and_forbidden_samples_carry_variants_and_anti_signals():
    """Anti-hardcoding (packet §5.1): each required/forbidden sample must justify
    its tool expectation with paraphrase variants AND anti-signals, so the eval
    cannot collapse to a single keyword/title match."""
    for s in samples.REGISTRY.values():
        if s.tool_expectation in (samples.REQUIRED, samples.FORBIDDEN):
            assert len(s.objective_variants) >= 2, s.sample_id
            assert len(set(s.objective_variants)) == len(s.objective_variants), s.sample_id
            assert s.anti_signals, s.sample_id
            # computational_property explains WHY (not just a title/keyword).
            assert len(s.computational_property) >= 20, s.sample_id


def test_no_sample_carries_forbidden_fields():
    """The registry is desensitised: no prompt/stem/answer/code/tests/keys/etc."""
    for s in samples.REGISTRY.values():
        leaked = {f for f in dir(s) if not f.startswith("_") and f in FORBIDDEN_FIELD_NAMES}
        assert not leaked, f"{s.sample_id} carries forbidden fields {leaked}"


def test_coding_samples_declare_a_single_language():
    for s in samples.samples_for(samples.PRACTICE_CODING):
        assert s.language in ("python", "java", "cpp")


def test_suitability_is_structural_not_keyword_based_counterfactual():
    """Two lessons with IDENTICAL objective text but DIFFERENT structural flags
    get different coding suitability — suitability is driven by the profile, not
    by title/keyword matching (Spec 004 §6.2, ADR 006 §2.6)."""
    same_text = "work with the material"
    algo = LessonLearningProfile(objective_keys=[same_text], evidence_keys=["e1"],
                                 has_algorithmic_objective=True, has_executable_evidence=True)
    concept = LessonLearningProfile(objective_keys=[same_text], evidence_keys=["e1"],
                                    has_algorithmic_objective=False, has_executable_evidence=False)
    algo_coding = next(s for s in determine_suitability(algo, code_capability_ready=True)
                       if s.item_type.value == "coding")
    concept_coding = next(s for s in determine_suitability(concept, code_capability_ready=True)
                          if s.item_type.value == "coding")
    assert algo_coding.status == SuitabilityStatus.SUPPORTED
    assert concept_coding.status == SuitabilityStatus.UNSUPPORTED


def test_negative_control_profile_rejects_coding_and_science_modes():
    """The concept negative-control sample's profile must make require_coding and
    require_science fail type suitability (the lesson has no executable/computable
    target), proving 'forbidden' is structural."""
    s = samples.NEGATIVE_CONCEPT_ENGINEERING
    suit = determine_suitability(_profile(s), code_capability_ready=True, science_capability_ready=True)
    coding = next(x for x in suit if x.item_type.value == "coding")
    science = next(x for x in suit if x.item_type.value == "scientific")
    assert coding.status == SuitabilityStatus.UNSUPPORTED
    assert science.status == SuitabilityStatus.UNSUPPORTED
    assert validate_item_type_mode(ItemTypeMode.REQUIRE_CODING, suit) == "coding_item_not_supported_by_lesson"
    assert validate_item_type_mode(ItemTypeMode.REQUIRE_SCIENCE, suit) == "science_item_not_supported_by_lesson"


def test_coding_and_science_profiles_are_supported_when_capability_ready():
    for s in (samples.PRACTICE_CODING_IDENTITY, samples.PRACTICE_SCIENCE_SYMBOLIC):
        suit = determine_suitability(_profile(s), code_capability_ready=True, science_capability_ready=True)
        target = "coding" if s.capability == samples.PRACTICE_CODING else "scientific"
        entry = next(x for x in suit if x.item_type.value == target)
        assert entry.status == SuitabilityStatus.SUPPORTED, s.sample_id
