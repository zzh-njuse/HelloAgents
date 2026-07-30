"""Test-only fake execution backend for Slice 2B Batch B (packet §5).

This is a CONTROLLED backend, NOT the real Judge0 VM. It speaks the minimal
Judge0-style synchronous submission contract that the product MCP execution
adapter (``apps/mcp_execution/adapter.py::_run_via_judge0``) posts to:

    POST /submissions?wait=true&base64_encoded=false
    body: {source_code, language_id, stdin}
    ->  {status:{id,description}, stdout, stderr, compile_output, exit_code}

It DETERMINISTICALLY supports Python/Java/C++ by ACTUALLY compiling and running
the canonical harness the product builds (``_build_coding_harness``) on the real
local toolchain. For a correct reference the harness prints
``{"passed":N,"total":N}`` and this server returns Accepted (id 3) with that
stdout, so the real product validation path sees a genuine pass. A broken
reference yields a real compile_error (id 6) or a real test mismatch. This is
faithful controlled behaviour, never a fake "passed".

It exposes safe reset/counters endpoints that return ONLY the scenario, the
call count and a stable classification — never request bodies, source, stdout,
stderr, paths or keys (packet §5.8/§5.9). Scenario reset and counter increment
are atomic under one lock (no Slice 2A reset race).

Scenarios:
- default        -> honest compile+run.
- infra_failure  -> HTTP 503 so the adapter maps it to BackendUnavailableError
                    (used only for the system infrastructure counterfactual).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def _path(target: str) -> str:
    """Strip the query string so /submissions?wait=true matches /submissions."""
    return urlparse(target).path

LOCK = threading.Lock()
ACTIVE_SCENARIO = "default"
COUNTS: dict[str, int] = {}
PORT = int(os.environ.get("FAKE_EXEC_PORT", "8110"))
RUN_TIMEOUT = float(os.environ.get("FAKE_EXEC_TIMEOUT_SECONDS", "10"))

# Judge0 language ids (mirror apps/mcp_execution/adapter.py::JUDGE0_LANGUAGE_MAP)
LANG_PYTHON = 71
LANG_JAVA = 62
LANG_CPP = 54


def _json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _next_count() -> tuple[str, int]:
    """Atomically read the active scenario and increment its call counter.

    Reading ``ACTIVE_SCENARIO`` and bumping its counter must happen inside the
    SAME ``LOCK`` critical section, and the caller must use ONLY this snapshot.
    If the read and the increment were split across two lock acquisitions, a
    concurrent ``/__reset`` could switch the scenario in between — crediting this
    request to scenario A's counter while the response is generated for scenario
    B (the Slice 2A reset race). Returning ``(scenario, count)`` here makes the
    whole request use one atomic snapshot (packet Fix 4).
    """
    with LOCK:
        scenario = ACTIVE_SCENARIO
        current = COUNTS.get(scenario, 0) + 1
        COUNTS[scenario] = current
        return scenario, current


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, timeout=RUN_TIMEOUT,
        text=True, encoding="utf-8", errors="replace", env=env,
    )


def _execute(source_code: str, language_id: int) -> dict:
    """Compile+run the harness and map the outcome to a Judge0 result dict."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            if language_id == LANG_PYTHON:
                path = os.path.join(tmp, "harness.py")
                with open(path, "w", encoding="utf-8") as h:
                    h.write(source_code)
                proc = _run(["python", path])
                stage = "run"
            elif language_id == LANG_JAVA:
                path = os.path.join(tmp, "Main.java")
                with open(path, "w", encoding="utf-8") as h:
                    h.write(source_code)
                cp = _run(["javac", "-encoding", "UTF-8", path])
                if cp.returncode != 0:
                    return {"status": {"id": 6, "description": "Compilation Error"},
                            "stdout": None, "stderr": None,
                            "compile_output": cp.stderr or cp.stdout or "", "exit_code": None}
                proc = _run(["java", "-cp", tmp, "Main"])
                stage = "run"
            elif language_id == LANG_CPP:
                src = os.path.join(tmp, "harness.cpp")
                exe = os.path.join(tmp, "harness.exe")
                with open(src, "w", encoding="utf-8") as h:
                    h.write(source_code)
                cp = _run(["g++", "-std=c++17", "-fexec-charset=UTF-8", src, "-o", exe])
                if cp.returncode != 0:
                    return {"status": {"id": 6, "description": "Compilation Error"},
                            "stdout": None, "stderr": None,
                            "compile_output": cp.stderr or cp.stdout or "", "exit_code": None}
                proc = _run([exe])
                stage = "run"
            else:
                return {"status": {"id": 6, "description": "Compilation Error"},
                        "compile_output": "unsupported language", "stdout": None,
                        "stderr": None, "exit_code": None}
        except subprocess.TimeoutExpired:
            return {"status": {"id": 5, "description": "Time Limit Exceeded"},
                    "stdout": None, "stderr": None, "compile_output": None, "exit_code": None}

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if proc.returncode == 0:
            return {"status": {"id": 3, "description": "Accepted"},
                    "stdout": stdout, "stderr": stderr, "compile_output": None, "exit_code": 0}
        return {"status": {"id": 7, "description": "Runtime Error"},
                "stdout": stdout, "stderr": stderr, "compile_output": None, "exit_code": proc.returncode}


class Handler(BaseHTTPRequestHandler):
    server_version = "HelloAgentsFakeExec/1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = _path(self.path)
        if path == "/readyz":
            _json(self, 200, {"ready": True, "reason_code": "ok"})
            return
        if path == "/__healthz":
            # Bare readiness for a HEAD probe (adapter /readyz does HEAD on the
            # backend root). Return 200 with a minimal body.
            _json(self, 200, {"ready": True})
            return
        if path.startswith("/__calls/"):
            scenario = path.rsplit("/", 1)[-1]
            with LOCK:
                count = COUNTS.get(scenario, 0)
            _json(self, 200, {"scenario": scenario, "count": count})
            return
        # Root HEAD/GET used by the adapter readiness probe.
        _json(self, 200, {"ready": True, "reason_code": "ok"})

    def do_HEAD(self) -> None:
        # The execution adapter's /readyz does a HEAD against the backend root.
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            _json(self, 400, {"error": "invalid_json"})
            return

        path = _path(self.path)
        if path == "/__reset":
            global ACTIVE_SCENARIO
            scenario = str(payload.get("scenario", "default"))
            with LOCK:
                ACTIVE_SCENARIO = scenario
                COUNTS[scenario] = 0
            _json(self, 200, {"scenario": scenario, "count": 0})
            return

        if path != "/submissions":
            _json(self, 404, {"error": "not_found"})
            return

        # One atomic snapshot: the scenario credited (counter) is exactly the
        # scenario the response is generated for. No second read of the global
        # ACTIVE_SCENARIO (packet Fix 4).
        scenario, _count = _next_count()
        if scenario == "infra_failure":
            # Adapter maps 503 -> BackendUnavailableError -> MCP tool error.
            _json(self, 503, {"error": "stub_backend_unavailable"})
            return

        result = _execute(
            str(payload.get("source_code", "")),
            int(payload.get("language_id", 0)),
        )
        _json(self, 200, result)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
