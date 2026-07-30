"""Controlled subprocess-environment tests (C++ Gate acceptance fix).

These are unit/diagnostic tests for the controlled compiler environment — NOT
the coding baseline Gate. They prove:

- the compiler subprocess receives a controlled env whose PATH puts the resolved
  compiler's OWN directory first, so its sub-processes (cc1plus/as/ld) and
  dynamically-linked runtimes resolve DLLs from the install dir even when the
  inherited PATH leads with a conflicting directory (the ``0xC0000139`` /
  incompatible-DLL root cause);
- ``os.environ`` is never mutated and Java/Python bind to their OWN dirs, never
  the g++ dir;
- the honest-fail Gate (RuntimeError, not skip) is preserved.

They do not require Postgres and do not contact any network.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from quality_baseline import controlled


# ---------------------------------------------------------------------------
# 1. Env construction: prepends, full env preserved, os.environ untouched
# ---------------------------------------------------------------------------

def test_env_with_dir_first_prepends_without_mutating_os_environ(monkeypatch, tmp_path):
    marker = str(tmp_path / "inherited_marker")
    original = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", marker + os.pathsep + original)

    env = controlled._env_with_dir_first(r"C:\some\compiler\bin")

    assert env is not os.environ  # a fresh dict, not the live mapping
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == r"C:\some\compiler\bin"  # dir first
    assert parts[1] == marker                    # inherited PATH follows
    # The system environment is unchanged.
    assert os.environ["PATH"] == marker + os.pathsep + original


def test_env_for_returns_none_for_unresolvable_binary(monkeypatch):
    monkeypatch.setenv("PATH", "")  # nothing resolvable
    assert controlled._env_for("definitely_no_such_compiler_xyz") is None


# ---------------------------------------------------------------------------
# 2. Priority counterfactual (requirement 7)
# ---------------------------------------------------------------------------

def test_env_for_prioritizes_resolved_dir_over_conflicting_inherited_path(monkeypatch, tmp_path):
    """When the inherited PATH leads with a conflicting directory, the resolved
    binary's OWN directory still takes priority in the controlled env."""
    binary = sys.executable  # always present; proves the mechanism without g++
    own_dir = os.path.dirname(binary)
    conflict = str(tmp_path / "conflict_dir")
    original = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", conflict + os.pathsep + original)

    env = controlled._env_for(binary)

    assert env is not None
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == own_dir
    assert parts.index(own_dir) < parts.index(conflict)  # own dir BEFORE conflict
    # os.environ not mutated by the helper.
    assert os.environ["PATH"].split(os.pathsep)[0] == conflict


def test_env_for_resolves_per_binary_not_global_gpp():
    """Requirement 6: each binary binds to ITS OWN dir, never the g++ dir."""
    py_env = controlled._env_for(sys.executable)
    assert py_env is not None
    assert py_env["PATH"].split(os.pathsep)[0] == os.path.dirname(sys.executable)

    gpp = shutil.which("g++")
    if gpp is not None:
        gpp_env = controlled._env_for("g++")
        assert gpp_env["PATH"].split(os.pathsep)[0] == os.path.dirname(gpp)
        # Python's controlled env must not lead with the g++ dir.
        assert py_env["PATH"].split(os.pathsep)[0] != os.path.dirname(gpp)


# ---------------------------------------------------------------------------
# 3. End-to-end counterfactual with the REAL g++ (requirement 7)
# ---------------------------------------------------------------------------

def test_cpp_gate_compiles_when_inherited_path_leads_with_conflicting_dir(monkeypatch, tmp_path):
    """Counterfactual: with a conflicting directory leading the INHERITED PATH,
    the compiler's own runtime dir still wins and the real C++ preflight + a
    real harness compile succeed. ``os.environ`` is restored afterward."""
    gpp = shutil.which("g++")
    assert gpp is not None, "g++ required for the C++ gate — honest fail, not skip"
    conflict = tmp_path / "conflict_dir"
    conflict.mkdir()
    original_path = os.environ.get("PATH", "")
    # Inherited PATH leads with a conflicting directory (simulates a Conda base
    # or any dir whose DLLs would shadow the compiler's runtimes).
    monkeypatch.setenv("PATH", str(conflict) + os.pathsep + original_path)

    controlled.reset_preflight_cache()
    try:
        state, diag = controlled._preflight("cpp")
        assert state == "ok", diag
        # A real compile+run through the SAME controlled env used by the harness.
        result, _handshake = controlled.controlled_execute_code_run_sync(
            "req", "cpp", "int main() { return 0; }", "", None)
        assert result.status == "completed", (result.status, result.stderr)
    finally:
        controlled.reset_preflight_cache()
    # monkeypatch restores os.environ at teardown.


def test_cpp_success_subprocesses_receive_resolved_gpp_dir_first(monkeypatch):
    """Platform-neutral contract proof (CI runs ubuntu-latest): on the SUCCESS
    path every compiler subprocess driven by the C++ preflight AND the real
    harness — version probe, flagged compile, harness compile and harness run —
    receives a controlled env whose PATH leads with the resolved g++ directory.

    This verifies the env WIRING directly. It deliberately does NOT assume any
    OS DLL-search behavior (which differs between Windows/MSYS2 and Linux and
    would make a "remove dir -> must fail" assertion environment-specific)."""
    gpp = shutil.which("g++")
    assert gpp is not None, "g++ required for the C++ gate — honest fail, not skip"
    gpp_dir = os.path.dirname(gpp)

    captured: list[tuple[list[str], dict[str, str] | None]] = []
    real = controlled._run_subprocess

    def spy(cmd, *, env=None):
        captured.append((list(cmd), env))
        return real(cmd, env=env)

    monkeypatch.setattr(controlled, "_run_subprocess", spy)
    controlled.reset_preflight_cache()
    try:
        assert controlled._preflight("cpp")[0] == "ok"
        result, _handshake = controlled.controlled_execute_code_run_sync(
            "req", "cpp", "int main() { return 0; }", "", None)
        assert result.status == "completed", (result.status, result.stderr)
    finally:
        controlled.reset_preflight_cache()

    assert captured, "no subprocess observed"
    # Every subprocess the C++ path drove must carry a controlled env whose PATH
    # leads with the resolved g++ dir.
    for cmd, env in captured:
        assert env is not None, f"subprocess launched without a controlled env: {cmd}"
        assert env["PATH"].split(os.pathsep)[0] == gpp_dir, (
            f"subprocess PATH does not lead with the g++ dir: {cmd}")
    # And the operations enumerated in requirement 4 were genuinely exercised.
    assert any("--version" in c for c, _ in captured), "version probe not observed"
    assert any("-fexec-charset=UTF-8" in c for c, _ in captured), "flagged compile not observed"
    assert any(len(c) == 1 for c, _ in captured), "harness run not observed"


def test_cpp_bare_probe_receives_resolved_gpp_dir_first_on_failure(monkeypatch):
    """Platform-neutral: on the FAILURE path the bare isolation probe runs too.
    Force only the flagged compile to fail and assert the version probe, the
    flagged compile AND the bare probe all receive the controlled env (PATH leads
    with the resolved g++ dir). Again, this asserts wiring, not OS DLL behavior."""
    gpp = shutil.which("g++")
    assert gpp is not None, "g++ required for the C++ gate — honest fail, not skip"
    gpp_dir = os.path.dirname(gpp)

    captured: list[tuple[list[str], dict[str, str] | None]] = []
    real = controlled._run_subprocess

    class _ForcedFailure:
        returncode = 1
        stdout = ""
        stderr = "forced flagged-compile failure (env spy)"

    def spy(cmd, *, env=None):
        captured.append((list(cmd), env))
        # Force ONLY the flagged compile (carries -fexec-charset) to fail so the
        # bare-probe branch executes; version probe and bare probe run for real.
        if any("-fexec-charset" in part for part in cmd):
            return _ForcedFailure()
        return real(cmd, env=env)

    monkeypatch.setattr(controlled, "_run_subprocess", spy)
    controlled.reset_preflight_cache()
    try:
        state, diag = controlled._preflight("cpp")
        assert state == "broken", diag
        assert "bare_compile_rc=" in diag, diag  # bare probe ran
    finally:
        controlled.reset_preflight_cache()

    for cmd, env in captured:
        assert env is not None, f"subprocess launched without a controlled env: {cmd}"
        assert env["PATH"].split(os.pathsep)[0] == gpp_dir, (
            f"subprocess PATH does not lead with the g++ dir: {cmd}")
    # version probe, flagged compile and bare probe all observed.
    assert any("--version" in c for c, _ in captured), "version probe not observed"
    assert any(any("-fexec-charset" in x for x in c) for c, _ in captured), "flagged compile not observed"
    assert any("--version" not in c and not any("-fexec-charset" in x for x in c) and "-o" in c
               for c, _ in captured), "bare probe not observed"


# ---------------------------------------------------------------------------
# 4. Honest-fail Gate preserved (requirement 8)
# ---------------------------------------------------------------------------

def test_require_toolchain_ok_raises_when_compiler_absent(monkeypatch):
    """The Gate FAILs (RuntimeError) when the compiler is absent — never skips
    or fakes a pass."""
    monkeypatch.setattr(controlled.shutil, "which", lambda b: None)
    controlled.reset_preflight_cache()
    try:
        with pytest.raises(RuntimeError, match="cpp toolchain is absent"):
            controlled.require_toolchain_ok("cpp")
    finally:
        controlled.reset_preflight_cache()


# ---------------------------------------------------------------------------
# 5. Absolute-path redaction (packet Fix 2): spaced paths, both separators,
#    POSIX roots, and ordinary prose must be preserved.
# ---------------------------------------------------------------------------

def test_redact_windows_path_with_spaces_is_fully_masked():
    out = controlled._redact_paths("fatal in C:\\Program Files\\app\\bin\\tool.cpp at line 5")
    assert "Program" not in out and "tool.cpp" not in out and "C:\\" not in out
    assert "<path>" in out
    # Leading prose survives. Ambiguous trailing text is masked with the path:
    # confidentiality takes priority over preserving the entire diagnostic.
    assert "fatal in" in out


def test_redact_windows_forward_slash_form_is_fully_masked():
    # Both separator forms (C:\ and C:/) must be masked; the drive must not leak.
    bs = controlled._redact_paths("err C:\\Users\\me\\src\\main.cpp done")
    fs = controlled._redact_paths("err C:/Users/me/src/main.cpp done")
    for out in (bs, fs):
        assert "Users" not in out and "main.cpp" not in out
        assert "<path>" in out and "err" in out
        assert "C:" not in out  # drive letter must not survive


def test_redact_posix_path_with_spaces_is_fully_masked():
    out = controlled._redact_paths("see /usr/local/my dir/bin/tool for details")
    assert "usr" not in out and "local" not in out and "tool" not in out
    assert "<path>" in out and "see" in out


def test_redact_posix_root_only_at_token_boundary():
    """A slash inside ordinary prose (input/output, 3/4) is NOT a path root and
    must not be masked; a standalone POSIX path is."""
    prose = controlled._redact_paths("the input/output ratio is 3/4 here")
    assert "input/output" in prose and "3/4" in prose
    assert "<path>" not in prose
    rooted = controlled._redact_paths("root is /etc/passwd ok")
    assert "etc" not in rooted and "<path>" in rooted and "root is" in rooted


def test_redact_preserves_ordinary_diagnostic_text():
    """Normal diagnostic prose is not deleted wholesale (packet Fix 2)."""
    msg = "compilation finished with 3 errors and 2 warnings"
    out = controlled._redact_paths(msg)
    assert out == msg  # no path root -> untouched, not collapsed to <path>


def test_redact_helper_keeps_path_output_contract_and_limit():
    # The integrated _redact still masks paths and keeps the length cap + <path>.
    out = controlled._redact("err C:\\Program Files\\app\\tool.cpp more", limit=40)
    assert "<path>" in out
    assert "Program" not in out
    assert len(out) <= 40


@pytest.mark.parametrize("diagnostic, forbidden", [
    ("err C:\\Users\\John Doe", ("C:\\", "John", "Doe")),
    ("err C:/Users/John Doe/file name.cpp:10:2", ("C:/", "Users", "file name.cpp")),
    ("err /home/John Doe", ("/home", "John", "Doe")),
    ("err /tmp/file name.cpp:10", ("/tmp", "file name.cpp")),
])
def test_redact_masks_spaced_terminal_path_components(diagnostic, forbidden):
    out = controlled._redact_paths(diagnostic)
    assert "<path>" in out
    assert out.startswith("err ")
    for fragment in forbidden:
        assert fragment not in out
