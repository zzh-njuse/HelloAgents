"""Focused unit tests for the Slice 2B controlled stub servers (packet Fix 4/5).

These test the STUB SERVER LOGIC directly (in-process), NOT the Compose system
Gate. They deliberately live outside the two files the system-test-runner
collects (``test_practice_vertical.py`` / ``test_tutor_tools_vertical.py``), so
the system Gate stays at 11 while these contracts are verified locally:

- Fix 4: the fake execution backend reads the active scenario and increments its
  counter in ONE atomic critical section, returning ``(scenario, count)``. A
  request can never be counted against scenario A while responded as B, even
  under an interleaved scenario switch.
- Fix 5: the model-services stub fails explicitly (a stable, prompt/secret-free
  HTTP error) on the first over-quota call instead of repeating the last
  response; the normal sequence is unchanged.

No Postgres, no Redis, no Compose, no real network egress — the server modules
are loaded by path and (for Fix 5) served on a loopback ephemeral port.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
from pathlib import Path

import httpx
import pytest

_SYSTEM_DIR = Path(__file__).resolve().parent


def _load_module(rel: str):
    path = _SYSTEM_DIR / rel
    spec = importlib.util.spec_from_file_location(path.stem + "_stub_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_exec_server():
    srv = _load_module(os.path.join("fake_execution_backend", "server.py"))
    srv.ACTIVE_SCENARIO = "default"
    srv.COUNTS.clear()
    return srv


@pytest.fixture
def model_stub_server():
    srv = _load_module(os.path.join("model_services_stub", "server.py"))
    srv.ACTIVE_SCENARIO = "success"
    srv.SCENARIOS.clear()
    return srv


# ---------------------------------------------------------------------------
# Fix 4: fake execution backend — scenario + count are one atomic snapshot
# ---------------------------------------------------------------------------

def test_fake_exec_next_count_returns_scenario_and_count(fake_exec_server):
    srv = fake_exec_server
    srv.ACTIVE_SCENARIO = "alpha"
    assert srv._next_count() == ("alpha", 1)
    assert srv._next_count() == ("alpha", 2)
    assert srv.COUNTS == {"alpha": 2}


def test_fake_exec_scenario_switch_does_not_leak_count(fake_exec_server):
    """Switching the active scenario does not credit the new scenario with the
    previous scenario's count (sequential isolation)."""
    srv = fake_exec_server
    srv.ACTIVE_SCENARIO = "A"
    srv._next_count()
    srv._next_count()  # A -> 2
    srv.ACTIVE_SCENARIO = "B"
    assert srv._next_count() == ("B", 1)
    assert srv.COUNTS == {"A": 2, "B": 1}


def test_fake_exec_count_never_credited_to_wrong_scenario_under_switch_race(fake_exec_server):
    """Concurrent / interleaved reset counterfactual (packet Fix 4). Under an
    interleaved scenario switch, every returned ``(scenario, count)`` must belong
    to the scenario whose counter was actually incremented. If the scenario read
    were split from the increment (the Slice 2A reset race), a call could be
    counted against A but returned as B — and the per-scenario contiguity
    invariant below would then break."""
    srv = fake_exec_server
    srv.ACTIVE_SCENARIO = "A"
    srv.COUNTS.clear()
    n_threads = 8
    iters = 300
    results: list[tuple[str, int]] = []
    results_lock = threading.Lock()
    stop = threading.Event()

    def caller():
        local = [srv._next_count() for _ in range(iters)]
        with results_lock:
            results.extend(local)

    def switcher():
        # The switching half of a reset, taken under the SAME lock the server
        # uses, WITHOUT zeroing — this isolates read-vs-increment atomicity.
        while not stop.is_set():
            with srv.LOCK:
                srv.ACTIVE_SCENARIO = "B" if srv.ACTIVE_SCENARIO == "A" else "A"

    threads = [threading.Thread(target=caller) for _ in range(n_threads)]
    switch = threading.Thread(target=switcher)
    switch.start()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    switch.join()

    # Every call was counted exactly once.
    assert len(results) == n_threads * iters
    # No duplicate (scenario, count) pair: each scenario's counter is monotonic.
    assert len(set(results)) == len(results)
    # Per scenario the returned counts form a contiguous 1..K set with no gaps.
    # A gap would mean a count was attributed to the wrong scenario.
    by_scenario = {"A": set(), "B": set()}
    for scenario, count in results:
        assert scenario in by_scenario, f"unexpected scenario: {scenario!r}"
        by_scenario[scenario].add(count)
    for scenario, counts in by_scenario.items():
        assert counts == set(range(1, len(counts) + 1)), (
            f"scenario {scenario!r} counts are not contiguous 1..K: {sorted(counts)}")


# ---------------------------------------------------------------------------
# Fix 5: model-services stub — over-quota call fails explicitly
# ---------------------------------------------------------------------------

def _serve(srv_module):
    httpd = srv_module.ThreadingHTTPServer(("127.0.0.1", 0), srv_module.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


@pytest.fixture
def stub_http(model_stub_server):
    httpd, port = _serve(model_stub_server)
    base = f"http://127.0.0.1:{port}"
    # trust_env=False: talk to the loopback server directly, ignoring any
    # HTTP_PROXY/HTTPS_PROXY in the environment (which would 502 on localhost).
    client = httpx.Client(base_url=base, trust_env=False, timeout=5)
    try:
        yield model_stub_server, client
    finally:
        client.close()
        httpd.shutdown()
        httpd.server_close()


def test_model_stub_normal_sequence_is_unchanged(stub_http):
    """The legitimate ordinal sequence still returns its locked responses,
    unchanged by the over-quota guard (packet Fix 5)."""
    srv, client = stub_http
    client.post("/__reset", json={"scenario": "tutor_code_required"})
    sequence = srv.SCENARIO_RESPONSES["tutor_code_required"]
    for expected in sequence:
        resp = client.post("/chat/completions", json={})
        assert resp.status_code == 200
        content = json.loads(resp.json()["choices"][0]["message"]["content"])
        assert content == expected
    assert srv.SCENARIOS["tutor_code_required"] == len(sequence)


def test_model_stub_over_quota_call_fails_explicitly(stub_http):
    """The FIRST call past the locked sequence must fail with a stable,
    diagnostic, prompt/secret-free HTTP error — never a silent repeat of the
    last response (packet Fix 5)."""
    srv, client = stub_http
    client.post("/__reset", json={"scenario": "tutor_code_required"})
    sequence = srv.SCENARIO_RESPONSES["tutor_code_required"]
    for _ in sequence:  # consume the legitimate sequence (each 200)
        assert client.post("/chat/completions", json={}).status_code == 200
    # First over-quota call: explicit failure.
    over = client.post("/chat/completions", json={})
    assert over.status_code == 409
    body = over.json()
    assert body["error"] == "stub_scenario_exhausted"
    assert body["scenario"] == "tutor_code_required"
    assert body["ordinal"] == len(sequence) + 1
    assert body["sequence_length"] == len(sequence)
    # Stable + no prompt/secret/key/URL leakage in the error body.
    text = json.dumps(body)
    for needle in ("prompt", "messages", "Authorization", "Bearer", "api_key",
                   "http://", "https://"):
        assert needle not in text


def test_model_stub_over_quota_does_not_repeat_last_response(stub_http):
    """The over-quota response is NOT the last legitimate response in disguise."""
    srv, client = stub_http
    client.post("/__reset", json={"scenario": "practice_java_success"})
    sequence = srv.SCENARIO_RESPONSES["practice_java_success"]
    for _ in sequence:
        client.post("/chat/completions", json={})
    over = client.post("/chat/completions", json={})
    assert over.status_code == 409  # not 200 repeating the last body
    assert over.text != json.dumps(sequence[-1])
