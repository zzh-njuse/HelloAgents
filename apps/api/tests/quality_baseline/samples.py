"""Allowlisted sample registry for the Slice 2B Batch A quality baseline.

Each sample is a machine-readable, desensitised contract entry (Spec 007 §4.1,
Slice 2B packet §5). A sample ONLY carries:

- a stable ``sample_id``;
- the ``capability`` axis it probes;
- desensitised objective/evidence categories and the *structural*
  ``computational_property`` that makes a tool required/optional/forbidden;
- request mode, total item count and a single code language;
- the ``tool_expectation`` (required|optional|forbidden) and the contract
  classification it is meant to exercise;
- paraphrase ``objective_variants`` and ``anti_signals`` so the eval cannot
  degenerate into keyword/title matching (packet §5.1);
- a structural ``profile`` (the lesson's learning-target flags) that drives the
  REAL ``determine_suitability`` — suitability is structural, never keyword-based.

A sample NEVER contains: real user profile data, lesson source text, stems,
answers, reference code, hidden tests, rubrics, provider raw responses, prompts,
keys, URLs or absolute paths. Those live only as clearly-marked controlled test
inputs in ``controlled.py`` / the test modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Capability axes accepted by Spec 007 §4.1.
PRACTICE_CODING = "practice_coding"
PRACTICE_SCIENCE = "practice_science"
TUTOR_CODE = "tutor_code"
TUTOR_SCIENCE = "tutor_science"
NEGATIVE_CONTROL = "negative_control"

CAPABILITIES = (PRACTICE_CODING, PRACTICE_SCIENCE, TUTOR_CODE, TUTOR_SCIENCE, NEGATIVE_CONTROL)

# Tool expectations (Spec 007 §4.2).
REQUIRED = "required"
OPTIONAL = "optional"
FORBIDDEN = "forbidden"

TOOL_EXPECTATIONS = (REQUIRED, OPTIONAL, FORBIDDEN)


@dataclass(frozen=True)
class Sample:
    sample_id: str
    capability: str
    objective_kind: str            # desensitised objective category
    evidence_kind: str             # desensitised evidence category
    computational_property: str    # structural reason tool is required/optional/forbidden
    tool_expectation: str          # required|optional|forbidden
    contract_target: str           # which contract classification this probes
    request_mode: str              # auto|require_coding|require_science|tutor
    item_count: int
    language: str | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    objective_variants: tuple[str, ...] = ()
    anti_signals: tuple[str, ...] = ()

    def __post_init__(self):
        if self.capability not in CAPABILITIES:
            raise ValueError(f"sample {self.sample_id}: unknown capability {self.capability!r}")
        if self.tool_expectation not in TOOL_EXPECTATIONS:
            raise ValueError(f"sample {self.sample_id}: unknown tool_expectation {self.tool_expectation!r}")
        if self.capability == PRACTICE_CODING and not self.language:
            raise ValueError(f"sample {self.sample_id}: practice_coding needs a single language")
        # Anti-hardcoding guard (packet §5.1): a required/forbidden sample must
        # carry paraphrase variants AND anti-signals, so the eval cannot collapse
        # to a single keyword/title match.
        if self.tool_expectation in (REQUIRED, FORBIDDEN):
            if len(self.objective_variants) < 2:
                raise ValueError(f"sample {self.sample_id}: need >=2 objective_variants")
            if not self.anti_signals:
                raise ValueError(f"sample {self.sample_id}: need >=1 anti_signal")


def _coding_profile() -> dict[str, Any]:
    return {"algorithmic": True, "executable": True, "math": False,
            "physics": False, "chemistry": False, "computable": False}


def _science_profile() -> dict[str, Any]:
    return {"algorithmic": False, "executable": False, "math": True,
            "physics": False, "chemistry": False, "computable": True}


def _concept_profile() -> dict[str, Any]:
    return {"algorithmic": False, "executable": False, "math": False,
            "physics": False, "chemistry": False, "computable": False}


# --- Coding (practice_coding) — tool REQUIRED: deterministic I/O transform -----

PRACTICE_CODING_IDENTITY = Sample(
    sample_id="practice_coding_identity",
    capability=PRACTICE_CODING,
    objective_kind="algorithmic_utf8_transform",
    evidence_kind="executable_io_contract",
    computational_property="deterministic input/output transform over a UTF-8 string that "
                           "requires an in-place/whole-string algorithm with exact assertions",
    tool_expectation=REQUIRED,
    contract_target="coding_reference_passes; specialized item == 1; deterministic grading",
    request_mode="require_coding",
    item_count=1,
    language="python",
    profile=_coding_profile(),
    objective_variants=(
        "return the input string unchanged",
        "map each input to itself",
        "identity transformation of a unicode string",
    ),
    anti_signals=(
        "pure definitional question with no input/output contract",
        "memorise a single keyword and print it",
    ),
)

PRACTICE_CODING_REVERSE = Sample(
    sample_id="practice_coding_reverse",
    capability=PRACTICE_CODING,
    objective_kind="algorithmic_string_reversal",
    evidence_kind="executable_io_contract_multiline",
    computational_property="reverse a (possibly multi-line) UTF-8 string with exact assertions "
                           "exercising canonical wrapper/entrypoint for a non-Python language",
    tool_expectation=REQUIRED,
    contract_target="coding_reference_passes; java canonical wrapper; multiline/UTF-8 IO",
    request_mode="require_coding",
    item_count=1,
    language="java",
    profile=_coding_profile(),
    objective_variants=(
        "reverse the order of characters in the input",
        "produce the mirror image of the string",
        "output the input read backwards",
    ),
    anti_signals=(
        "explain the concept of reversal in prose",
        "a conceptual question that needs no executable program",
    ),
)

PRACTICE_CODING_AGGREGATE = Sample(
    sample_id="practice_coding_aggregate",
    capability=PRACTICE_CODING,
    objective_kind="algorithmic_aggregate",
    evidence_kind="executable_io_contract",
    computational_property="compute an aggregate (e.g. transform/case-map) over the input requiring "
                           "a bounded loop with exact deterministic assertions",
    tool_expectation=REQUIRED,
    contract_target="coding_reference_passes; cpp canonical wrapper; compile-error classification",
    request_mode="require_coding",
    item_count=1,
    language="cpp",
    profile=_coding_profile(),
    objective_variants=(
        "apply a deterministic per-character transform",
        "fold the input into a normalized form",
        "map every character by a fixed rule",
    ),
    anti_signals=(
        "describe the rule without executing it",
        "a reading-comprehension item with no code contract",
    ),
)

# --- Science (practice_science) — REQUIRED / OPTIONAL / (forbidden via concept) --

PRACTICE_SCIENCE_SYMBOLIC = Sample(
    sample_id="practice_science_symbolic_integral",
    capability=PRACTICE_SCIENCE,
    objective_kind="symbolic_indefinite_integral",
    evidence_kind="computable_symbolic_expression",
    computational_property="symbolic indefinite integral whose equivalence cannot be decided by a "
                           "local numeric rule — genuinely requires external symbolic verification",
    tool_expectation=REQUIRED,
    contract_target="succeeded_with_wolfram; VerifyScientificAnswer succeeded; Set published",
    request_mode="require_science",
    item_count=1,
    language=None,
    profile=_science_profile(),
    objective_variants=(
        "find the antiderivative of a polynomial",
        "integrate the given expression symbolically",
        "determine the closed-form primitive",
    ),
    anti_signals=(
        "a numeric plug-in evaluation a local rule can decide",
        "a purely conceptual definition of integration",
    ),
)

PRACTICE_SCIENCE_UNIT = Sample(
    sample_id="practice_science_unit_constant",
    capability=PRACTICE_SCIENCE,
    objective_kind="physics_unit_constant_computation",
    evidence_kind="computable_physical_quantity",
    computational_property="physics computation involving a physical constant / unit conversion whose "
                           "magnitude benefits from external numeric verification",
    tool_expectation=REQUIRED,
    contract_target="succeeded_with_wolfram; VerifyScientificAnswer succeeded",
    request_mode="require_science",
    item_count=1,
    language=None,
    profile={"algorithmic": False, "executable": False, "math": False,
             "physics": True, "chemistry": False, "computable": True},
    objective_variants=(
        "compute the quantity using the stated physical constant",
        "convert and evaluate the physical relationship",
        "evaluate the formula with the given units",
    ),
    anti_signals=(
        "state the definition of the constant from memory",
        "a conceptual physics question with no computation",
    ),
)

PRACTICE_SCIENCE_LOCAL_NUMERIC = Sample(
    sample_id="practice_science_local_numeric",
    capability=PRACTICE_SCIENCE,
    objective_kind="numeric_tolerance_evaluation",
    evidence_kind="computable_numeric_value",
    computational_property="a numeric answer within an explicit tolerance that a local deterministic "
                           "rule can decide — Wolfram is OPTIONAL, not required",
    tool_expectation=OPTIONAL,
    contract_target="succeeded_without_wolfram; local rule sufficient; zero remote call",
    request_mode="require_science",
    item_count=1,
    language=None,
    profile=_science_profile(),
    objective_variants=(
        "evaluate the expression to a number within tolerance",
        "compute the numeric result",
        "estimate the value to the given precision",
    ),
    anti_signals=(
        "a symbolic identity a local rule cannot decide",
        "a conceptual question with no numeric target",
    ),
)

# --- Negative control — tool FORBIDDEN: pure concept, no executable/computable target

NEGATIVE_CONCEPT_ENGINEERING = Sample(
    sample_id="negative_concept_engineering",
    capability=NEGATIVE_CONTROL,
    objective_kind="concept_software_engineering_tradeoff",
    evidence_kind="narrative_concept",
    computational_property="a pure management/concept tradeoff with no executable skill and no "
                           "computable target — coding/Wolfram would add no value",
    tool_expectation=FORBIDDEN,
    contract_target="tool_not_needed; zero tool calls; general items only; require_coding/require_science rejected",
    request_mode="auto",
    item_count=3,
    language=None,
    profile=_concept_profile(),
    objective_variants=(
        "discuss the tradeoff between two development modes",
        "explain when one organisational pattern is preferable",
        "compare the costs of two engineering approaches",
    ),
    anti_signals=(
        "an algorithmic task with a deterministic input/output contract",
        "a numeric/symbolic computation with a verifiable answer",
    ),
)

# --- Tutor code — REQUIRED / FORBIDDEN -----------------------------------------

TUTOR_CODE_REQUIRED = Sample(
    sample_id="tutor_code_required",
    capability=TUTOR_CODE,
    objective_kind="tutor_demonstrate_algorithm_behavior",
    evidence_kind="executable_behavior_question",
    computational_property="the question is about the runtime behaviour of a small program; running "
                           "it yields the observation the Tutor needs to answer honestly",
    tool_expectation=REQUIRED,
    contract_target="McpCodeTool succeeded; run_code authorised+called; observation informs answer",
    request_mode="tutor",
    item_count=1,
    language="python",
    objective_variants=(
        "what does this snippet output when run",
        "trace the execution and give the result",
        "run this and tell me the observed value",
    ),
    anti_signals=(
        "a conceptual explanation that needs no execution",
        "a definition question answerable from the text",
    ),
)

TUTOR_CODE_NOT_NEEDED = Sample(
    sample_id="tutor_code_not_needed",
    capability=TUTOR_CODE,
    objective_kind="tutor_concept_explanation",
    evidence_kind="narrative_concept",
    computational_property="a conceptual explanation where executing code adds no value; even when "
                           "authorised, the Tutor must keep zero code calls",
    tool_expectation=FORBIDDEN,
    contract_target="zero McpCodeTool calls even when code authorised (negative control)",
    request_mode="tutor",
    item_count=1,
    language="python",
    objective_variants=(
        "explain the idea in plain terms",
        "describe when the approach is used",
        "summarise the concept for review",
    ),
    anti_signals=(
        "a question that asks for the output of a concrete program",
        "a task that requires observing runtime behaviour",
    ),
)

# --- Tutor Wolfram — REQUIRED / FORBIDDEN -------------------------------------

TUTOR_SCIENCE_REQUIRED = Sample(
    sample_id="tutor_science_required",
    capability=TUTOR_SCIENCE,
    objective_kind="tutor_symbolic_computation",
    evidence_kind="computable_symbolic_expression",
    computational_property="a symbolic computation question whose answer benefits from external "
                           "verification; the Tutor should request and use the observation",
    tool_expectation=REQUIRED,
    contract_target="McpScienceTool succeeded; WolframAlpha/Context authorised+called; answer uses observation",
    request_mode="tutor",
    item_count=1,
    language=None,
    objective_variants=(
        "compute the symbolic result",
        "evaluate the expression and verify it",
        "derive the closed-form answer",
    ),
    anti_signals=(
        "a definitional question answerable from the material",
        "a concept question with nothing to compute",
    ),
)

TUTOR_SCIENCE_NOT_NEEDED = Sample(
    sample_id="tutor_science_not_needed",
    capability=TUTOR_SCIENCE,
    objective_kind="tutor_definitional_question",
    evidence_kind="narrative_concept",
    computational_property="a definitional/conceptual question where Wolfram adds no value; even when "
                           "authorised, the Tutor must keep zero science calls",
    tool_expectation=FORBIDDEN,
    contract_target="zero McpScienceTool calls even when science authorised (negative control)",
    request_mode="tutor",
    item_count=1,
    language=None,
    objective_variants=(
        "define the term in your own words",
        "explain what the concept means",
        "describe the property being asked about",
    ),
    anti_signals=(
        "a question that asks to compute or verify a symbolic expression",
        "a task requiring numeric/symbolic evaluation",
    ),
)


REGISTRY: dict[str, Sample] = {s.sample_id: s for s in (
    PRACTICE_CODING_IDENTITY, PRACTICE_CODING_REVERSE, PRACTICE_CODING_AGGREGATE,
    PRACTICE_SCIENCE_SYMBOLIC, PRACTICE_SCIENCE_UNIT, PRACTICE_SCIENCE_LOCAL_NUMERIC,
    NEGATIVE_CONCEPT_ENGINEERING,
    TUTOR_CODE_REQUIRED, TUTOR_CODE_NOT_NEEDED,
    TUTOR_SCIENCE_REQUIRED, TUTOR_SCIENCE_NOT_NEEDED,
)}


def samples_for(capability: str) -> list[Sample]:
    return [s for s in REGISTRY.values() if s.capability == capability]


def by_id(sample_id: str) -> Sample:
    if sample_id not in REGISTRY:
        raise KeyError(f"unknown sample_id {sample_id!r}; not in allowlisted registry")
    return REGISTRY[sample_id]
