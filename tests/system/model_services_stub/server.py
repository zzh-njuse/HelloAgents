from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


LOCK = threading.Lock()
SCENARIOS: dict[str, int] = {}
ACTIVE_SCENARIO = "success"
PORT = int(os.environ.get("STUB_PORT", "8090"))


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _next_call() -> tuple[str, int]:
    """Atomically read the active scenario and increment its call counter.

    Reading ACTIVE_SCENARIO and bumping its own counter must happen inside the
    same LOCK critical section. If the read and the increment were split across
    two lock acquisitions, a concurrent ``/__reset`` could switch the scenario
    in between, crediting this call to the new scenario's counter while the
    response was generated for the old one (Slice 2A reset race).
    """
    with LOCK:
        scenario = ACTIVE_SCENARIO
        current = SCENARIOS.get(scenario, 0) + 1
        SCENARIOS[scenario] = current
        return scenario, current


# ---------------------------------------------------------------------------
# Fixed, desensitised controlled test artifacts (Slice 2B Batch B packet §6).
#
# These JSON bodies are the ONLY provider outputs the new scenarios emit. They
# are positional: each scenario locks an ordinal -> response contract. They
# never depend on the inbound prompt text (no keyword guessing) and carry no
# real user data, prompts, keys or URLs. They prove system wiring, state, MCP
# and UI — NOT that a fixed answer is "correct" product intent.
# ---------------------------------------------------------------------------

_USAGE = {"prompt_tokens": 50, "completion_tokens": 120}


def _practice_plan() -> dict:
    # Practice search/plan step (Exercise Author plan): 1-3 queries.
    return {"queries": ["objective evidence", "method evidence"]}


def _coding_item(item_key: str, language: str) -> dict:
    # A valid v2 coding item whose reference solution genuinely passes the
    # canonical harness (identity transform). The fake execution backend runs
    # the real harness and produces {"passed":N,"total":N} -> Accepted.
    ref = {
        "python": "def solve(input_text):\n    return input_text",
        "java": "class Solution { static String solve(String input) { return input; } }",
        "cpp": "std::string solve(const std::string& input){ return input; }",
    }[language]
    return {
        "item_key": item_key,
        "target_key": "objective_1",
        "item_type": "coding",
        "stem": "Read one UTF-8 string and return it unchanged.",
        "citation_ids": ["e1"],
        "language": language,
        "input_description": "one UTF-8 string",
        "output_description": "the same string unchanged",
        "constraints": ["1 <= len(input) <= 1000"],
        "public_examples": [{"input": "demo", "expected_output": "demo", "weight": 1, "is_public": True}],
        "hidden_tests": [
            {"input": "alpha", "expected_output": "alpha", "weight": 1},
            {"input": "hello", "expected_output": "hello", "weight": 1},
            {"input": "x", "expected_output": "x", "weight": 1},
        ],
        "reference_solution": ref,
    }


def _scientific_item(item_key: str, *, needs_remote: bool) -> dict:
    # needs_remote=True  -> Wolfram-REQUIRED sample (symbolic verification at
    #   generation time via needs_remote_verification; equivalence_rule="exact"
    #   so grading is decided locally without a second remote call).
    # needs_remote=False -> Wolfram-not-needed sample (local numeric grading,
    #   zero remote calls even when authorized) — the negative control.
    if needs_remote:
        spec = {
            "normalized_answer": "x^3/3",
            "tolerance": None,
            "unit": None,
            "equivalence_rule": "exact",
            "needs_remote_verification": True,
            "verification_expression": "Integrate[x^2, x]",
        }
    else:
        spec = {
            "normalized_answer": "42",
            "tolerance": 0.5,
            "unit": None,
            "equivalence_rule": "numeric_tolerance",
            "needs_remote_verification": False,
            "verification_expression": None,
        }
    return {
        "item_key": item_key,
        "target_key": "objective_1",
        "item_type": "scientific",
        "stem": "Compute the requested result and show the worked steps.",
        "citation_ids": ["e1"],
        "reference_answer": "Worked solution deriving the answer step by step.",
        "rubric": [
            {"criterion_key": "c1", "description": "Correct result", "weight": 60, "citation_ids": ["e1"]},
            {"criterion_key": "c2", "description": "Valid derivation", "weight": 40, "citation_ids": ["e1"]},
        ],
        "scientific_answer_spec": spec,
    }


def _grading_feedback(score: int = 100) -> dict:
    # A valid PracticeFeedbackArtifact for scientific/short-answer rubric
    # grading. A perfect score requires every criterion fully met.
    met = "full" if score == 100 else "partial"
    return {
        "verdict": "correct" if score == 100 else "partially_correct",
        "score": score,
        "criterion_results": [
            {"criterion_key": "c1", "met": met, "note": "Result assessed.", "citation_ids": ["e1"]},
            {"criterion_key": "c2", "met": met, "note": "Derivation assessed.", "citation_ids": ["e1"]},
        ],
        "blocks": [
            {"block_key": "fb1", "type": "explanation", "text": "The worked solution is assessed against the rubric.", "citation_ids": ["e1"]}
        ],
    }


def _tutor_plan(*, code_requests: list, science_requests: list) -> dict:
    return {
        "intent": "concept_explanation",
        "queries": ["binary search halving"],
        "learning_context_use": "irrelevant",
        "teaching_moves": ["explain", "check"],
        "science_requests": science_requests,
        "code_requests": code_requests,
    }


def _tutor_answer(*, with_science_observation: bool = False, with_code_observation: bool = False) -> dict:
    blocks = [
        {
            "block_key": "answer",
            "type": "direct_answer",
            "text": "Binary search halves the remaining sorted interval.",
            "citation_ids": ["e1"],
        },
        {
            "block_key": "check",
            "type": "check_question",
            "text": "What condition lets binary search discard half of the interval?",
            "citation_ids": [],
        },
    ]
    if with_science_observation:
        blocks.append({
            "block_key": "science_obs",
            "type": "science_observation",
            "text": "The symbolic result was verified by the computation tool.",
            "citation_ids": [],
        })
    if with_code_observation:
        blocks.append({
            "block_key": "code_obs",
            "type": "code_observation",
            "text": "Running the small program confirmed the observed behaviour.",
            "citation_ids": [],
        })
    return {"blocks": blocks}


# Scenario -> ordered response sequence (1-indexed by ordinal). Each entry is a
# JSON object returned as the chat completion content. The sequences are locked
# by the packet §6 ordinal contract.
PYTHON_PRINT = "print('5')\n"  # tiny runnable program for tutor code_requests
SCENARIO_RESPONSES: dict[str, list[dict]] = {
    # Practice coding (java/cpp): plan, generation, grading(fallback ok for coding).
    "practice_java_success": [_practice_plan(), {"items": [_coding_item("c1", "java")]}, {}],
    "practice_cpp_success": [_practice_plan(), {"items": [_coding_item("c1", "cpp")]}, {}],
    # Counterfactual (§12): a C++ item whose reference genuinely fails to
    # compile, then an invalid repair DTO -> the Job must fail and publish no
    # Set (reference_failed_tests / coding_repair_artifact_invalid).
    "practice_cpp_compile_fail": [
        _practice_plan(),
        {"items": [{
            **_coding_item("c1", "cpp"),
            "reference_solution": "std::string solve(const std::string& input){ return input ",
        }]},
        {},
    ],
    # Practice science required: plan, generation(scientific needs_remote), grading feedback.
    "practice_science_wolfram_required": [
        _practice_plan(),
        {"items": [_scientific_item("s1", needs_remote=True)]},
        _grading_feedback(100),
    ],
    # Practice science negative: tool-not-needed sample, zero remote even if authorized.
    "practice_science_negative": [
        _practice_plan(),
        {"items": [_scientific_item("s1", needs_remote=False)]},
        _grading_feedback(100),
    ],
    # Tutor code required: plan requests a code run; answer uses the observation.
    "tutor_code_required": [
        _tutor_plan(code_requests=[{"language": "python", "source_code": PYTHON_PRINT, "stdin": ""}], science_requests=[]),
        _tutor_answer(with_code_observation=True),
    ],
    # Tutor code negative: authorized but model requests no code -> zero execution calls.
    "tutor_code_negative": [_tutor_plan(code_requests=[], science_requests=[]), _tutor_answer()],
    # Tutor Wolfram required: plan requests an allowlisted science tool; answer uses result.
    "tutor_wolfram_required": [
        _tutor_plan(code_requests=[], science_requests=[{"tool": "WolframAlpha", "arguments": {"query": "Integrate[x^2, x]"}}]),
        _tutor_answer(with_science_observation=True),
    ],
    # Tutor Wolfram negative: authorized but model requests no science -> zero calls.
    "tutor_wolfram_negative": [_tutor_plan(code_requests=[], science_requests=[]), _tutor_answer()],
}


def _chat_content(scenario: str, ordinal: int) -> dict[str, object]:
    # Legacy Slice 2A tutor scenarios (success/repair/timeout/failure) keep
    # their original behaviour unchanged.
    plan = {
        "intent": "concept_explanation",
        "queries": ["binary search halving"],
        "learning_context_use": "irrelevant",
        "teaching_moves": ["explain", "check"],
        "science_requests": [],
        "code_requests": [],
    }
    answer = {
        "blocks": [
            {
                "block_key": "answer",
                "type": "direct_answer",
                "text": "Binary search halves the remaining sorted interval.",
                "citation_ids": ["e1"],
            },
            {
                "block_key": "check",
                "type": "check_question",
                "text": "What condition lets binary search discard half of the interval?",
                "citation_ids": [],
            },
        ]
    }
    if scenario == "repair" and ordinal == 2:
        return {"blocks": []}
    return plan if ordinal == 1 else answer


class Handler(BaseHTTPRequestHandler):
    server_version = "HelloAgentsModelStub/1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/readyz":
            _json(self, 200, {"ok": True})
            return
        if self.path.startswith("/__calls/"):
            scenario = self.path.rsplit("/", 1)[-1]
            with LOCK:
                count = SCENARIOS.get(scenario, 0)
            _json(self, 200, {"scenario": scenario, "count": count})
            return
        _json(self, 404, {"error": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            _json(self, 400, {"error": "invalid_json"})
            return

        if self.path == "/__reset":
            global ACTIVE_SCENARIO
            scenario = str(payload.get("scenario", "success"))
            with LOCK:
                ACTIVE_SCENARIO = scenario
                SCENARIOS[scenario] = 0
            _json(self, 200, {"scenario": scenario, "count": 0})
            return

        if self.path == "/embeddings":
            texts = payload.get("input", {}).get("texts", [])
            dimension = int(payload.get("parameters", {}).get("dimension", 4))
            vector = [1.0] + [0.0] * max(0, dimension - 1)
            _json(
                self,
                200,
                {"output": {"embeddings": [{"embedding": vector} for _ in texts]}},
            )
            return

        if self.path != "/chat/completions":
            _json(self, 404, {"error": "not_found"})
            return

        scenario, ordinal = _next_call()
        if scenario == "timeout":
            time.sleep(float(os.environ.get("STUB_TIMEOUT_SECONDS", "5")))
        if scenario == "failure":
            _json(self, 503, {"error": "stub_failure"})
            return

        if scenario in SCENARIO_RESPONSES:
            sequence = SCENARIO_RESPONSES[scenario]
            if ordinal > len(sequence):
                # Over-quota: the orchestration requested more provider calls
                # than this scenario's locked sequence provides. Fail explicitly
                # and stably instead of silently repeating the last response,
                # which would mask a budget/ordinal leak (packet Fix 5). The body
                # carries no prompt, secret, key or URL — only stable diagnostics.
                _json(self, 409, {
                    "error": "stub_scenario_exhausted",
                    "scenario": scenario,
                    "ordinal": ordinal,
                    "sequence_length": len(sequence),
                })
                return
            content = sequence[ordinal - 1]
        else:
            content = _chat_content(scenario, ordinal)
        _json(
            self,
            200,
            {
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": _USAGE,
            },
        )


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
