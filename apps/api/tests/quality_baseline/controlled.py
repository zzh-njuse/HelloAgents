"""Controlled backends for the Slice 2B Batch A baseline.

These replace only the lowest-level external boundaries while the REAL business
orchestration (plan, authorize, budget, immutability, authority commit) runs
unchanged:

- ``controlled_execute_code_run_sync`` runs the REAL product coding harness
  (``_build_coding_harness_for_version``) on the REAL local toolchain
  (``python``/``javac``/``g++``) and returns a ``RunCodeResult``. This is a
  CONTROLLED backend: it proves the canonical wrapper, UTF-8/multiline I/O and
  compile/runtime classification through the real harness + real compilers, but
  it is NOT the real Judge0 VM. Every run is tagged ``controlled_backend`` and
  must never be reported as a real Judge0 pass (Spec 007 §9.1, packet §7.2).
- scripted providers / science verifier / capability projection are pure test
  doubles that never contact a network, never read keys, and never log prompts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

# Re-exported so tests can construct the real product result types.
from learn_platform_api.services.code_lab_execution import (
    McpHandshakeSnapshot, RunCodeResult,
)
from learn_platform_api.services.science_tool_service import ScienceToolResult

TIMEOUT_SECONDS = 20
OUTPUT_LIMIT_BYTES = 1_000_000

# Controlled handshake snapshot — placeholder hashes; the practice orchestration
# discards the handshake, so this never participates in schema-drift checks.
_CONTROLLED_HANDSHAKE = McpHandshakeSnapshot(
    server_name="controlled", server_version="controlled",
    protocol_version="2025-11-25", tool_name="run_code",
    input_schema_hash="c" * 16, output_schema_hash="d" * 16,
)

# Module flag: every coding run in this baseline used the controlled backend,
# never the real Judge0 VM. Reports read this to label ``controlled_backend``.
CONTROLLED_BACKEND = True


# ---------------------------------------------------------------------------
# Diagnostic sanitization — compiler output may only surface as a stable,
# length-limited, path-free string (Spec 007 §10, packet §4).
# ---------------------------------------------------------------------------

_DIAG_LIMIT = 400

# Path-root detection (packet Fix 2). A Windows absolute path starts with a
# drive letter followed by a separator in EITHER form — ``C:\`` or ``C:/`` — so
# both separator forms are masked. A POSIX absolute path starts with ``/`` at a
# token boundary (start-of-string or after a non-alphanumeric char), so the slash
# inside ordinary prose such as ``input/output`` or ``3/4`` is NOT a path root.
_WIN_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
_POSIX_ROOT_RE = re.compile(r"(?<![A-Za-z0-9])/")
# Characters that never appear inside a path body (hard terminators).
_PATH_STOPPERS = frozenset("\n\"'<>|")


def _path_end(text: str, start: int) -> int:
    """Index just past a path body that begins at ``start`` (right after a root).

    A path body may contain spaces (including in its final component) and a
    gcc-style ``:line:col`` suffix. Because an unquoted path and following prose
    are ambiguous, consume through the next hard delimiter. This deliberately
    favors preventing local-path disclosure over preserving same-line prose.
    """
    # An unquoted final path component may itself contain spaces. Once an
    # absolute root is recognized there is no reliable way to distinguish that
    # component from prose later on the same line. Prefer confidentiality:
    # consume the ambiguous remainder up to a hard delimiter.
    i = start
    n = len(text)
    while i < n and text[i] not in _PATH_STOPPERS:
        i += 1
    return i


def _redact_paths(text: str) -> str:
    """Replace every absolute path with ``<path>`` (the ``_ABS_PATH_RE``
    equivalent implementation, packet Fix 2).

    Fully masks Windows drive roots with BOTH separators (``C:\\..`` and
    ``C:/..``), Windows and POSIX paths that contain spaces, and POSIX roots only
    at a token boundary. Non-path text — including prose with mid-word slashes —
    is left intact; the ``<path>`` output contract is unchanged.
    """
    if not text:
        return ""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if _WIN_DRIVE_RE.match(text, i):
            i = _path_end(text, i + 3)  # past "X:\" / "X:/"
            out.append("<path>")
            continue
        if _POSIX_ROOT_RE.match(text, i):
            i = _path_end(text, i + 1)  # past "/"
            out.append("<path>")
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _redact(text: str, *dirs: str, limit: int = 0) -> str:
    """Strip temp dirs and ANY absolute path, then collapse whitespace.

    Compiler stderr/stdout is never persisted verbatim; only this stable,
    path-free excerpt may appear in a preflight diagnostic. ``limit`` truncates
    the final string (0 = no truncation). Path masking is delegated to
    ``_redact_paths``.
    """
    if not text:
        return ""
    out = text
    for d in dirs:
        if d:
            out = out.replace(d, "<tmp>")
    out = _redact_paths(out)
    out = " ".join(out.split())
    return out[:limit] if limit else out


def _env_with_dir_first(directory: str) -> dict[str, str]:
    """Return a FRESH copy of ``os.environ`` with ``directory`` first on PATH.

    ``os.environ`` itself is never mutated; only the returned copy changes. The
    full environment is preserved (SYSTEMROOT/TEMP/PATHEXT/...) so the child
    still resolves system tools — only PATH is reordered.
    """
    env = dict(os.environ)
    existing = env.get("PATH", "")
    env["PATH"] = directory + os.pathsep + existing if existing else directory
    return env


def _env_for(binary: str) -> dict[str, str] | None:
    """Controlled env with the resolved binary's OWN directory first on PATH.

    ``binary`` may be a name (``"g++"``) or an absolute path (``sys.executable``);
    it is resolved with ``shutil.which``. Returns ``None`` only when it cannot be
    resolved. Resolution is strictly per-binary, so Java/Python bind to THEIR OWN
    install dirs and never to the g++ dir.

    Why: MSYS2 ``g++`` drives ``cc1plus``/``as``/``ld`` from its install dir, and
    those binaries plus the harness ``.exe`` dynamically link the ucrt64 runtime
    DLLs (libstdc++-6 / libgcc_s_* / libwinpthread-1) that live in the compiler's
    bin dir. When a conflicting directory (e.g. a Conda base) leads the inherited
    PATH, Windows loads an incompatible DLL and ``cc1plus`` exits ``0xC0000139``
    (STATUS_ENTRYPOINT_NOT_FOUND). Putting the compiler's own dir first lets its
    runtimes resolve correctly, with no change to the test process's PATH.
    """
    resolved = shutil.which(binary)
    if resolved is None:
        return None
    return _env_with_dir_first(os.path.dirname(resolved))


def _run_subprocess(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a compiler command capturing stdout/stderr as UTF-8.

    ``env`` (typically from ``_env_for``) is a controlled environment that puts
    the compiler's own directory first on PATH so its sub-processes and runtimes
    resolve their DLLs correctly; when ``None`` the child inherits ``os.environ``
    unchanged. ``text=True`` without an explicit encoding decodes with the system
    locale (cp936 on a Chinese Windows build), which can crash the read — or
    garble a UTF-8 compiler message — before the real error is ever seen. Forcing
    UTF-8 with ``errors="replace"`` guarantees a readable diagnostic.
    """
    return subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_SECONDS,
                          text=True, encoding="utf-8", errors="replace", env=env)


def _compiler_version(binary: str, *, env: dict[str, str] | None = None) -> str:
    """Best-effort first ``--version`` line, redacted of any path."""
    try:
        proc = _run_subprocess([binary, "--version"], env=env)
        line = (proc.stdout or "").splitlines()[0].strip() if proc.stdout else ""
    except Exception:
        line = ""
    return _redact(line) or "version unavailable"


# ---------------------------------------------------------------------------
# Real local toolchain preflight (absent / broken / ok) — never a fake pass.
# ---------------------------------------------------------------------------

_PREFLIGHT_CACHE: dict[str, tuple[str, str]] = {}


def _preflight(language: str) -> tuple[str, str]:
    if language in _PREFLIGHT_CACHE:
        return _PREFLIGHT_CACHE[language]
    if language == "python":
        # basename only — never leak the interpreter's absolute path.
        state, diag = "ok", f"python interpreter usable: {os.path.basename(sys.executable)}"
        _PREFLIGHT_CACHE[language] = (state, diag)
        return state, diag
    binary = "javac" if language == "java" else "g++"
    if shutil.which(binary) is None:
        state, diag = "absent", f"{binary} not on PATH"
        _PREFLIGHT_CACHE[language] = (state, diag)
        return state, diag
    # Controlled env: the compiler's OWN directory leads PATH so cc1plus/as/ld
    # and their DLLs resolve from the install dir, not a conflicting earlier
    # entry (the 0xC0000139 root cause). The SAME env is used for the version
    # probe, the flagged compile and the bare probe (requirement: one controlled
    # environment for all C++ compiles).
    env = _env_for(binary)
    version = _compiler_version(binary, env=env)
    with tempfile.TemporaryDirectory() as tmp:
        if language == "java":
            src = os.path.join(tmp, "Preflight.java")
            with open(src, "w", encoding="utf-8") as h:
                h.write("class Preflight { public static void main(String[] a) {} }\n")
            proc = _run_subprocess(["javac", "-encoding", "UTF-8", src], env=env)
        else:
            src = os.path.join(tmp, "preflight.cpp")
            exe = os.path.join(tmp, "preflight.exe")
            with open(src, "w", encoding="utf-8") as h:
                h.write("int main() { return 0; }\n")
            proc = _run_subprocess(["g++", "-std=c++17", "-fexec-charset=UTF-8", src, "-o", exe], env=env)
        if proc.returncode != 0:
            # Surface the real compiler message (sanitized, length-limited,
            # path-free) instead of only the exit code, so a failure is
            # reproducible/diagnosable across environments (packet §4).
            detail = _redact((proc.stderr or "") + " " + (proc.stdout or ""), tmp, limit=_DIAG_LIMIT)
            isolation = ""
            if language == "cpp":
                # Distinguish a flag/iconv failure from a broken compiler env:
                # retry the SAME source, SAME controlled env, with NO
                # -std/-fexec-charset flags.
                bare_exe = os.path.join(tmp, "preflight_bare.exe")
                try:
                    bare = _run_subprocess(["g++", src, "-o", bare_exe], env=env)
                    isolation = f" bare_compile_rc={bare.returncode}"
                    if bare.returncode != 0:
                        isolation += " detail=" + _redact(
                            (bare.stderr or "") + " " + (bare.stdout or ""), tmp, limit=200)
                except Exception as exc:
                    isolation = f" bare_probe_error={type(exc).__name__}"
            state = "broken"
            diag = (f"{binary} present ({version}) but trivial compile failed "
                    f"rc={proc.returncode}; detail={detail}{isolation}")
        else:
            state, diag = "ok", f"{binary} trivial compile ok ({version})"
    _PREFLIGHT_CACHE[language] = (state, diag)
    return state, diag


def reset_preflight_cache() -> None:
    """Clear the preflight cache (used by counterfactual tests that fake which())."""
    _PREFLIGHT_CACHE.clear()


def require_toolchain_ok(language: str) -> str:
    """Return the diagnostic for an ``ok`` toolchain.

    Raises ``RuntimeError`` (not skip) when the toolchain is absent or broken —
    the coding baseline Gate must FAIL honestly rather than silently pass or skip
    a language axis (Spec 007 §13, packet §7.2).
    """
    state, diag = _preflight(language)
    if state != "ok":
        raise RuntimeError(
            f"{language} toolchain is {state} — coding baseline Gate must FAIL, "
            f"not skip or fake a pass: {diag}"
        )
    return diag


# ---------------------------------------------------------------------------
# Real harness execution on the local toolchain → RunCodeResult
# ---------------------------------------------------------------------------


def _run_local(language: str, source_code: str) -> dict:
    """Compile+run a complete harness program on the real local toolchain.

    Returns ``{status, stdout, stderr, returncode, stage}`` where status is one
    of the fixed ``RunCodeResult`` statuses. Stderr is redacted of the temp dir
    and any host absolute path so no path can leak (stdout is the harness JSON,
    which carries only counts).
    """
    with tempfile.TemporaryDirectory() as tmp:
        if language == "python":
            path = os.path.join(tmp, "harness.py")
            with open(path, "w", encoding="utf-8") as h:
                h.write(source_code)
            # Python's own dir first (harmless; never the g++ dir).
            env = _env_for(sys.executable)
            try:
                proc = _run_subprocess([sys.executable, path], env=env)
            except subprocess.TimeoutExpired:
                return {"status": "timed_out", "stdout": "", "stderr": "", "returncode": -1, "stage": "python"}
            return {
                "status": "completed" if proc.returncode == 0 else "runtime_error",
                "stdout": proc.stdout or "", "stderr": _redact(proc.stderr or "", tmp),
                "returncode": proc.returncode, "stage": "python",
            }
        if language == "java":
            java_path = os.path.join(tmp, "Main.java")
            with open(java_path, "w", encoding="utf-8") as h:
                h.write(source_code)
            # JDK dir first for javac (compile) and java (run) — same install,
            # resolved per-binary; never the g++ dir.
            cp = _run_subprocess(["javac", "-encoding", "UTF-8", java_path], env=_env_for("javac"))
            if cp.returncode != 0:
                return {"status": "compile_error", "stdout": "", "returncode": cp.returncode,
                        "stderr": _redact(cp.stderr or "", tmp), "stage": "javac"}
            try:
                proc = _run_subprocess(["java", "-cp", tmp, "Main"], env=_env_for("java"))
            except subprocess.TimeoutExpired:
                return {"status": "timed_out", "stdout": "", "stderr": "", "returncode": -1, "stage": "java"}
            return {
                "status": "completed" if proc.returncode == 0 else "runtime_error",
                "stdout": proc.stdout or "", "stderr": _redact(proc.stderr or "", tmp),
                "returncode": proc.returncode, "stage": "java",
            }
        # cpp — the compiler's own dir must lead PATH for BOTH the compile (so
        # cc1plus/as/ld resolve) and the harness run (the .exe links the ucrt64
        # runtime DLLs), under the SAME controlled environment as the preflight.
        src_path = os.path.join(tmp, "harness.cpp")
        exe_path = os.path.join(tmp, "harness.exe")
        with open(src_path, "w", encoding="utf-8") as h:
            h.write(source_code)
        gpp_env = _env_for("g++")
        cp = _run_subprocess(["g++", "-std=c++17", "-fexec-charset=UTF-8", src_path, "-o", exe_path], env=gpp_env)
        if cp.returncode != 0:
            return {"status": "compile_error", "stdout": "", "returncode": cp.returncode,
                    "stderr": _redact(cp.stderr or "", tmp), "stage": "g++"}
        try:
            proc = _run_subprocess([exe_path], env=gpp_env)
        except subprocess.TimeoutExpired:
            return {"status": "timed_out", "stdout": "", "stderr": "", "returncode": -1, "stage": "cpp-run"}
        return {
            "status": "completed" if proc.returncode == 0 else "runtime_error",
            "stdout": proc.stdout or "", "stderr": _redact(proc.stderr or "", tmp),
            "returncode": proc.returncode, "stage": "cpp-run",
        }


def controlled_execute_code_run_sync(request_id, language, source_code, stdin, settings):
    """Drop-in for ``execute_code_run_sync`` using the REAL harness + local toolchain.

    The caller (``_validate_coding_reference_via_mcp`` / ``execute_coding_grading``)
    passes the COMPLETE harness program as ``source_code``. We run it on the real
    local compiler/runtime and map the outcome to the fixed ``RunCodeResult``
    contract. Marked ``controlled_backend`` — never the real Judge0 VM.
    """
    require_toolchain_ok(language)
    raw = _run_local(language, source_code)
    stdout = raw["stdout"]
    if len(stdout.encode("utf-8")) > OUTPUT_LIMIT_BYTES:
        status = "output_limited"
    else:
        status = raw["status"]
    result = RunCodeResult(
        status=status, exit_code=raw["returncode"], compile_output="",
        stdout=stdout, stderr=raw["stderr"], duration_ms=0, runtime="",
        stdout_truncated=False, stderr_truncated=False,
    )
    return result, _CONTROLLED_HANDSHAKE


# ---------------------------------------------------------------------------
# Scripted provider (lowest-level LLM HTTP boundary)
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Return successive ``(parsed_json, usage)`` tuples; asserts exhaustion.

    A scripted provider never contacts a network and carries no prompt text — it
    only hands the real orchestration the parsed JSON it would have received.
    """

    def __init__(self, responses: list[tuple[Any, dict]]):
        self._iter = iter(responses)
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        try:
            parsed, usage = next(self._iter)
        except StopIteration:
            raise AssertionError(
                f"scripted provider exhausted after {self.calls - 1} calls; "
                "orchestration requested more provider calls than the script provided"
            )
        return parsed, dict(usage)


def usage(*, input_tokens=100, output_tokens=50, finish_reason="stop") -> dict:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "finish_reason": finish_reason}


# ---------------------------------------------------------------------------
# Controlled science (Wolfram) verifier
# ---------------------------------------------------------------------------


def make_science_verifier(policy: str, *, error_code: str = "mcp_connection_failed"):
    """Build a controlled ``execute_science_verification`` replacement (Practice path).

    policy:
    - ``verified``        → success, observation verified True (succeeded_with_wolfram)
    - ``not_verified``    → success, observation says not-equivalent
                            (scientific_reference_unverified)
    - ``fail``            → success=False with ``error_code`` (tool stage failure)
    - ``invalid_result``  → success, observation with an ``error`` key (tool_result_invalid)
    """
    def _verifier(*, tool, arguments, settings, expected_schema_hash=None, timeout_seconds=None, **_kw):
        if policy == "verified":
            return ScienceToolResult(success=True, observation={"verified": True, "result": "ok"}, latency_ms=1)
        if policy == "not_verified":
            return ScienceToolResult(success=True, observation={"verified": False, "result": "different"}, latency_ms=1)
        if policy == "invalid_result":
            return ScienceToolResult(success=True, observation={"error": "tool_call_error"}, latency_ms=1)
        return ScienceToolResult(success=False, error_code=error_code, latency_ms=1)
    return _verifier


def controlled_tutor_science_backend(outcome: str):
    """Controlled replacement for ``tutor_generation._execute_science_tool_call``.

    This is the lowest-level fake Wolfram backend permitted by packet §9.2: it
    consumes the Turn authorization, records the ``McpScienceTool:<tool>``
    AgentToolCall with the controlled outcome, and returns a bounded observation
    — exactly the contract the real function has. Everything else (plan request,
    authorization gate, budget, limitation/repair handling) runs in the REAL
    orchestration, so the persisted chain is real orchestration evidence, not a
    hand-created row.

    outcome: ``ok`` | ``schema_drift`` | ``mcp_connection_failed`` | ``tool_call_error``
            | ``result_too_large`` | ``tool_not_found``
    """
    import hashlib
    import time as _time
    from learn_platform_api.db.models import AgentToolCall

    def _backend(db, settings, turn, auth, request, run, next_ordinal, started_at):
        auth.used_calls += 1
        db.flush()
        if outcome == "ok":
            observation = {"result": "controlled", "verified": True}
            status = "succeeded"
        else:
            observation = {"error": outcome}
            status = "failed"
        db.add(AgentToolCall(
            agent_run_id=run.id, workspace_id=turn.workspace_id,
            tool_name=f"McpScienceTool:{request.tool}", ordinal=next_ordinal(),
            status=status, input_hash=hashlib.sha256(request.tool.encode()).hexdigest()[:16],
            result_count=0, latency_ms=round((_time.perf_counter() - started_at) * 1000),
        ))
        return observation
    return _backend


# ---------------------------------------------------------------------------
# Valid provider artifact builders (controlled test inputs)
# ---------------------------------------------------------------------------

_BASE_TESTS = [
    {"input": "a", "expected_output": "a", "weight": 1},
    {"input": "b", "expected_output": "b", "weight": 1},
    {"input": "c", "expected_output": "c", "weight": 1},
]


def _identity_source(language: str) -> str:
    return {
        "python": "def solve(input_text):\n    return input_text",
        "java": "class Solution { static String solve(String input) { return input; } }",
        "cpp": "std::string solve(const std::string& input){ return input; }",
    }[language]


def _reverse_source(language: str) -> str:
    return {
        "python": "def solve(input_text):\n    return input_text[::-1]",
        "java": "class Solution { static String solve(String input) { return new StringBuilder(input).reverse().toString(); } }",
        "cpp": "std::string solve(const std::string& input){ std::string s=input; std::reverse(s.begin(), s.end()); return s; }",
    }[language]


def coding_item(item_key: str, language: str, *, reference_solution: str | None = None,
                hidden_tests: list[dict] | None = None, stem: str = "Implement the described transformation.",
                task: str = "identity") -> dict:
    """A valid v2 ``coding`` item artifact (controlled test input).

    ``task`` selects a canonical reference solution + matching hidden tests so the
    item genuinely exercises an executable skill (Spec 004 §6.2). The hidden tests
    stay private grading material — they never enter any report.
    """
    if reference_solution is None:
        reference_solution = _identity_source(language) if task == "identity" else _reverse_source(language)
    if hidden_tests is None:
        if task == "identity":
            hidden_tests = [
                {"input": "alpha", "expected_output": "alpha", "weight": 1},
                {"input": "hello", "expected_output": "hello", "weight": 1},
                {"input": "héllo", "expected_output": "héllo", "weight": 1},
            ]
            public = [{"input": "demo", "expected_output": "demo", "weight": 1, "is_public": True}]
        else:
            hidden_tests = [
                {"input": "abc", "expected_output": "cba", "weight": 1},
                {"input": "ab", "expected_output": "ba", "weight": 1},
                {"input": "x", "expected_output": "x", "weight": 1},
            ]
            public = [{"input": "demo", "expected_output": "omed", "weight": 1, "is_public": True}]
    else:
        public = [{"input": "demo", "expected_output": "demo", "weight": 1, "is_public": True}]
    return {
        "item_key": item_key, "target_key": "objective_1", "item_type": "coding",
        "stem": stem, "citation_ids": ["e1"], "language": language,
        "input_description": "one UTF-8 string", "output_description": "the transformed string",
        "constraints": ["1 <= len(input) <= 1000"],
        "public_examples": public,
        "hidden_tests": hidden_tests, "reference_solution": reference_solution,
    }


def scientific_item(item_key: str, *, needs_remote: bool = True,
                    verification_expression: str = "Integrate[x^2, x]",
                    equivalence_rule: str = "symbolic") -> dict:
    """A valid ``scientific`` item artifact (controlled test input).

    ``needs_remote=True`` models a Wolfram-REQUIRED sample (symbolic computation);
    ``False`` models an OPTIONAL sample (local numeric rule is sufficient).
    """
    spec = {
        "normalized_answer": "x^3/3", "tolerance": None, "unit": None,
        "equivalence_rule": equivalence_rule,
        "needs_remote_verification": needs_remote,
        "verification_expression": verification_expression if needs_remote else None,
    }
    return {
        "item_key": item_key, "target_key": "objective_1", "item_type": "scientific",
        "stem": "Compute the requested symbolic/numeric result and show the worked steps.",
        "citation_ids": ["e1"], "reference_answer": "Worked solution deriving the answer.",
        "rubric": [
            {"criterion_key": "c1", "description": "Correct result", "weight": 60, "citation_ids": ["e1"]},
            {"criterion_key": "c2", "description": "Valid derivation", "weight": 40, "citation_ids": ["e1"]},
        ],
        "scientific_answer_spec": spec,
    }


def single_choice_item(item_key: str, *, stem: str = "Choose the supported statement.") -> dict:
    return {
        "item_key": item_key, "target_key": "objective_1", "item_type": "single_choice",
        "stem": stem, "citation_ids": ["e1"],
        "options": [
            {"option_key": "a", "text": "Correct statement", "is_correct": True, "rationale": "ok", "citation_ids": ["e1"]},
            {"option_key": "b", "text": "Wrong statement", "is_correct": False, "rationale": "no", "citation_ids": ["e1"]},
        ],
    }


def short_answer_item(item_key: str, *, stem: str = "Explain the concept in one sentence.") -> dict:
    return {
        "item_key": item_key, "target_key": "objective_1", "item_type": "short_answer",
        "stem": stem, "citation_ids": ["e1"],
        "reference_answer": "reference explanation",
        "rubric": [{"criterion_key": "c1", "description": "Correctness", "weight": 100, "citation_ids": ["e1"]}],
    }


def general_items(n: int) -> list[dict]:
    """``n`` valid general (non-specialized) items with DISTINCT vocabulary.

    Stems use disjoint content words so the novelty near-duplicate detector
    (same target+type AND task-token Jaccard >= 0.5 AND char3-gram Jaccard
    >= 0.90) does not flag items inside one Set — which would trigger an extra
    repair provider call and muddy the budget-curve count contract.
    """
    choice_stems = [
        "Which option matches the observed runtime behaviour?",
        "Pick the statement that reflects the memory tradeoff.",
        "Choose the description fitting the release cadence.",
        "Select the claim consistent with the concurrency limit.",
        "Identify the option matching the storage boundary.",
        "Which choice aligns with the recovery procedure?",
    ]
    short_stems = [
        "Summarize why the pipeline halts on bad input.",
        "Explain how the index survives a restart.",
        "Describe when caching becomes a liability.",
        "Outline the steps the reconciler performs.",
        "State the effect of raising the batch ceiling.",
        "Justify the chosen serialization order.",
    ]
    items: list[dict] = []
    for i in range(n):
        if i % 2 == 0:
            items.append(single_choice_item(f"g{i}", stem=choice_stems[(i // 2) % len(choice_stems)]))
        else:
            items.append(short_answer_item(f"g{i}", stem=short_stems[(i // 2) % len(short_stems)]))
    return items


def practice_plan(queries: list[str] | None = None) -> dict:
    return {"queries": queries or ["objective evidence", "method evidence", "test evidence"]}


# --- Broken / wrong reference solutions (controlled failure inputs) ------------


def compile_error_source(language: str) -> str:
    """A reference that genuinely fails to COMPILE for java/cpp.

    Python is interpreted: a SyntaxError surfaces as a runtime exit, so Python
    has no compile-error classification (documented in the canonical harness
    matrix). This helper is only valid for java/cpp.
    """
    if language == "java":
        return "class Solution { static String solve(String input) { return input "
    if language == "cpp":
        return "std::string solve(const std::string& input){ return input "
    raise ValueError(f"no compile-error source for {language!r}; python is runtime-classified")


def wrong_output_source(language: str, task: str = "identity") -> str:
    """A reference that COMPILES and RUNS but produces wrong output (test_mismatch)."""
    if task == "identity":
        # Correct identity returns input; this returns a constant → fails tests.
        return {
            "python": "def solve(input_text):\n    return 'wrong'",
            "java": 'class Solution { static String solve(String input) { return "wrong"; } }',
            "cpp": 'std::string solve(const std::string& input){ return "wrong"; }',
        }[language]
    # reverse task: correct reverses; this returns input unchanged → fails.
    return _identity_source(language)


def coding_repair_dto(item_key: str, reference_solution: str) -> dict:
    """Minimal v2 specialized coding repair DTO (only reference_solution mutable)."""
    return {"item_key": item_key, "reference_solution": reference_solution}


def scientific_repair_dto(item_key: str, *, needs_remote: bool = True) -> dict:
    """Minimal v2 specialized scientific repair DTO.

    Only ``scientific_answer_spec`` and ``reference_answer`` are mutable; the rest
    of the item identity is pinned by the orchestration's immutability check.
    """
    return {
        "item_key": item_key,
        "scientific_answer_spec": {
            "normalized_answer": "x^3/3", "tolerance": None, "unit": None,
            "equivalence_rule": "symbolic",
            "needs_remote_verification": needs_remote,
            "verification_expression": "Integrate[x^2, x]" if needs_remote else None,
        },
        "reference_answer": "Worked solution deriving the answer.",
    }
