from academic_companion.practice_agents import (
    PracticeItemArtifact,
    PracticeAuthorRequest,
    RequiredScientificReferenceRepairArtifact,
    build_practice_generation_prompt,
    build_specialized_item_repair_prompt,
)
from learn_platform_api.services.science_tool_service import (
    science_observation_is_verified,
    science_observation_verification_outcome,
)


def _request(required_item_type):
    return PracticeAuthorRequest(
        lesson_title="Lesson",
        lesson_objective="Objective",
        learning_objectives=("Target",),
        item_count=1,
        allowed_item_types=("single_choice", "short_answer", required_item_type),
        code_languages=("java",) if required_item_type == "coding" else (),
        required_item_type=required_item_type,
    )


def test_require_coding_prompt_makes_specialized_item_and_language_mandatory():
    messages = build_practice_generation_prompt(
        _request("coding"), [{"citation_id": "e1", "text": "evidence"}]
    )
    system = messages[0]["content"]

    assert "Include exactly one coding item" in system
    assert "mandatory, not optional" in system
    assert "static String solve(String input)" in system
    assert "must omit or set null for options, rubric, reference_answer" in system


def test_cpp_generation_and_repair_prompts_pin_exact_signature():
    request = PracticeAuthorRequest(
        lesson_title="Lesson",
        lesson_objective="Objective",
        learning_objectives=("Target",),
        item_count=1,
        allowed_item_types=("single_choice", "short_answer", "coding"),
        code_languages=("cpp",),
        required_item_type="coding",
    )
    evidence = [{"citation_id": "e1", "text": "evidence"}]
    generation = " ".join(
        message["content"]
        for message in build_practice_generation_prompt(request, evidence)
    )
    failed_item = PracticeItemArtifact.model_validate(
        {
            "item_key": "q1",
            "target_key": "objective_1",
            "item_type": "coding",
            "stem": "Implement the identity function.",
            "citation_ids": ["e1"],
            "language": "cpp",
            "hidden_tests": [
                {"input": "a", "expected_output": "a", "weight": 34, "comparator": "normalized_text"},
                {"input": "b", "expected_output": "b", "weight": 33, "comparator": "normalized_text"},
                {"input": "c", "expected_output": "c", "weight": 33, "comparator": "normalized_text"},
            ],
            "reference_solution": "std::string solve(const std::string& input) { return input; }",
        }
    )
    repair = " ".join(
        message["content"]
        for message in build_specialized_item_repair_prompt(
            request,
            evidence,
            failed_item,
            category="compile_error",
            harness_version="canonical_string_v2",
        )
    )

    exact = "std::string solve(const std::string& input)"
    assert exact in generation
    assert exact in repair
    assert "do not pass the string by value" in generation.lower()
    assert "do not pass the string by value" in repair.lower()


def test_require_science_prompt_requires_remote_verification_expression():
    messages = build_practice_generation_prompt(
        _request("scientific"), [{"citation_id": "e1", "text": "evidence"}]
    )
    system = messages[0]["content"]

    assert "Include exactly one scientific item" in system
    assert "non-empty verification_expression" in system
    assert "needs_remote_verification=true" in system
    assert "literal value True" in system


def test_required_science_repair_keeps_remote_boolean_verification():
    request = _request("scientific")
    item = PracticeItemArtifact.model_validate(
        {
            "item_key": "q1",
            "target_key": "objective_1",
            "item_type": "scientific",
            "stem": "Compute the value.",
            "citation_ids": ["e1"],
            "rubric": [
                {
                    "criterion_key": "r1",
                    "description": "Correct computation",
                    "weight": 100,
                    "citation_ids": ["e1"],
                }
            ],
            "reference_answer": "A worked answer.",
            "scientific_answer_spec": {
                "normalized_answer": "2",
                "tolerance": 0,
                "unit": None,
                "equivalence_rule": "exact",
                "needs_remote_verification": True,
                "verification_expression": "1 + 1 == 2",
            },
        }
    )
    prompt = " ".join(
        message["content"]
        for message in build_specialized_item_repair_prompt(
            request,
            [{"citation_id": "e1", "text": "evidence"}],
            item,
            category="science_unverified",
            harness_version="scientific_v2",
        )
    )

    assert "needs_remote_verification MUST be true" in prompt
    assert "expected to evaluate to literal True" in prompt
    assert "a bare calculation is invalid" in prompt
    assert "'const': true" in prompt.lower()
    required = RequiredScientificReferenceRepairArtifact.model_validate(
        {
            "item_key": "q1",
            "reference_answer": "A worked answer.",
            "scientific_answer_spec": {
                "normalized_answer": "2",
                "tolerance": 0,
                "unit": None,
                "equivalence_rule": "exact",
                "needs_remote_verification": True,
                "verification_expression": "1 + 1 == 2",
            },
        }
    )
    assert required.scientific_answer_spec.needs_remote_verification is True


def test_real_wolfram_text_envelope_requires_explicit_true_result():
    assert science_observation_is_verified(
        {
            "text": (
                "<result query='1 + 1 == 2'>\n"
                "# Input\n1 + 1 = 2\n# Result\nTrue\n"
                "</result>"
            )
        }
    )
    assert not science_observation_is_verified(
        {
            "text": (
                "<result query='True == False'>\n"
                "# Input\nTrue = False\n# Result\nFalse\n"
                "</result>"
            )
        }
    )
    assert science_observation_verification_outcome(
        {
            "text": (
                "<result query='True == False'>\n"
                "# Input\nTrue = False\n# Result\nFalse\n"
                "</result>"
            )
        }
    ) == "not_verified"
    assert not science_observation_is_verified(
        {"text": "The query contains True but has no result envelope."}
    )
