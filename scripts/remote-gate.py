"""Manual Stage 5 real-provider / remote-tool acceptance gate.

This driver uses only public product HTTP APIs. It deliberately writes a
low-cardinality report: no prompts, questions, course text, answers, code,
tool output, URLs, credentials, absolute paths, or business object IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import httpx


TERMINAL = {
    "succeeded",
    "failed",
    "canceled",
    "queue_failed",
    "completed",
    "compile_error",
    "runtime_error",
    "timed_out",
    "output_limited",
}
RUN_TERMINAL = {"succeeded", "failed", "canceled"}
ALLOWED_RECORD_KEYS = {
    "sample_id",
    "capability",
    "language",
    "mode",
    "requested_item_count",
    "final_item_count",
    "repetition",
    "tool_expectation",
    "tool_authorized",
    "tool_called",
    "tool_succeeded",
    "provider_call_count",
    "provider_succeeded_count",
    "provider_failed_count",
    "repair_count",
    "mcp_call_count",
    "input_tokens",
    "output_tokens",
    "known_cost_cny",
    "unknown_cost_call_count",
    "agent_run_count",
    "latency_ms",
    "final_status",
    "failure_category",
    "business_error_category",
    "layer",
    "controlled_backend",
    "remote_not_run",
}
FORBIDDEN_REPORT_TERMS = {
    "prompt",
    "question",
    "answer",
    "evidence",
    "citation",
    "source_code",
    "stdin",
    "stdout",
    "stderr",
    "compile",
    "test_case",
    "tool_output",
    "provider_response",
    "api_key",
    "authorization",
    "url",
    "path",
    "workspace_id",
    "course_id",
    "lesson_id",
    "job_id",
    "turn_id",
    "run_id",
}


@dataclass(frozen=True)
class LessonRef:
    course_id: str
    course_version_id: str
    lesson_id: str
    lesson_version_id: str

    @classmethod
    def parse(cls, value: str) -> "LessonRef":
        parts = value.split(":")
        if len(parts) != 4 or any(not part.strip() for part in parts):
            raise argparse.ArgumentTypeError(
                "lesson refs must be course_id:course_version_id:lesson_id:lesson_version_id"
            )
        return cls(*parts)


class RemoteHttpError(RuntimeError):
    def __init__(self, status_code: int, error_code: str):
        super().__init__(f"http_{status_code}_{error_code}")
        self.status_code = status_code
        self.error_code = error_code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def safe_error_category(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    normalized = "".join(ch for ch in text.lower() if ch in allowed)
    return normalized[:80] or fallback


def assert_safe_report(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    for record in payload.get("records", []):
        unexpected = set(record) - ALLOWED_RECORD_KEYS
        if unexpected:
            raise RuntimeError(f"unsafe_report_keys:{','.join(sorted(unexpected))}")
    for term in FORBIDDEN_REPORT_TERMS:
        if f'"{term}"' in lowered:
            raise RuntimeError(f"unsafe_report_term:{term}")
    if "http://" in lowered or "https://" in lowered or ":\\" in serialized:
        raise RuntimeError("unsafe_report_location")


class RemoteGate:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.client = httpx.Client(
            base_url=args.api_url.rstrip("/"),
            timeout=httpx.Timeout(20.0),
            trust_env=False,
        )
        self.records: list[dict[str, Any]] = []
        self.completed_keys: set[str] = set()
        self.original_policy: bool | None = None
        self.started_at = utc_now()
        self._load_checkpoint()

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, path, **kwargs)
        if response.is_error:
            detail: Any = None
            try:
                detail = response.json().get("detail")
            except Exception:
                pass
            raise RemoteHttpError(
                response.status_code,
                safe_error_category(detail, "request_rejected"),
            )
        return response

    def _load_checkpoint(self) -> None:
        if not self.args.output.exists() or not self.args.resume:
            return
        raw = json.loads(self.args.output.read_text(encoding="utf-8"))
        assert_safe_report(raw)
        started_at = raw.get("started_at")
        if isinstance(started_at, str):
            self.started_at = datetime.fromisoformat(started_at)
        self.records = list(raw.get("records", []))
        self.completed_keys = {
            f"{r['sample_id']}:{r['repetition']}" for r in self.records
        }

    def _write(self) -> None:
        summary: dict[str, dict[str, int]] = {}
        for record in self.records:
            bucket = summary.setdefault(
                record["sample_id"], {"total": 0, "succeeded": 0, "failed": 0}
            )
            bucket["total"] += 1
            if record["final_status"] == "succeeded":
                bucket["succeeded"] += 1
            else:
                bucket["failed"] += 1
        payload = {
            "schema_version": "stage5_remote_gate_v1",
            "layer": "real_remote",
            "controlled_backend": False,
            "remote_not_run": False,
            "started_at": self.started_at.isoformat(),
            "updated_at": utc_now().isoformat(),
            "record_count": len(self.records),
            "summary": summary,
            "records": self.records,
        }
        assert_safe_report(payload)
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = self.args.output.with_suffix(self.args.output.suffix + ".new")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for attempt in range(6):
            try:
                os.replace(temp, self.args.output)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def _record(self, key: str, record: dict[str, Any]) -> None:
        record.update(
            {
                "layer": "real_remote",
                "controlled_backend": False,
                "remote_not_run": False,
            }
        )
        if set(record) != ALLOWED_RECORD_KEYS:
            missing = ALLOWED_RECORD_KEYS - set(record)
            extra = set(record) - ALLOWED_RECORD_KEYS
            raise RuntimeError(
                f"record_contract_drift:missing={sorted(missing)}:extra={sorted(extra)}"
            )
        self.records.append(record)
        self.completed_keys.add(key)
        self._write()
        print(
            f"GATE {record['sample_id']} #{record['repetition']}: "
            f"{record['final_status']} ({record['failure_category']})",
            flush=True,
        )

    def _base_record(
        self,
        *,
        sample_id: str,
        capability: str,
        repetition: int,
        language: str | None,
        mode: str,
        item_count: int | None,
        expectation: str,
        authorized: bool,
        latency_ms: int,
    ) -> dict[str, Any]:
        return {
            "sample_id": sample_id,
            "capability": capability,
            "language": language,
            "mode": mode,
            "requested_item_count": item_count,
            "final_item_count": None,
            "repetition": repetition,
            "tool_expectation": expectation,
            "tool_authorized": authorized,
            "tool_called": False,
            "tool_succeeded": False,
            "provider_call_count": 0,
            "provider_succeeded_count": 0,
            "provider_failed_count": 0,
            "repair_count": 0,
            "mcp_call_count": 0,
            "input_tokens": None,
            "output_tokens": None,
            "known_cost_cny": None,
            "unknown_cost_call_count": 0,
            "agent_run_count": 0,
            "latency_ms": latency_ms,
            "final_status": "failed",
            "failure_category": "unknown_error",
            "business_error_category": "none",
        }

    def preflight(self) -> None:
        ready = self._request("GET", "/ready").json()
        checks = ready.get("checks", {})
        required = ("postgres", "qdrant", "redis", "storage")
        if ready.get("status") != "ready" or any(
            not checks.get(name, {}).get("ok") for name in required
        ):
            raise RuntimeError("environment_failed")
        if not checks.get("code_execution", {}).get("ok"):
            raise RuntimeError("code_execution_not_ready")
        if not checks.get("science_tool", {}).get("ok"):
            raise RuntimeError("science_tool_not_ready")
        self._request(
            "GET", f"/api/v1/workspaces/{self.args.workspace_id}/mcp-capabilities"
        )

    def _wait_capability(self, capability: str, timeout: int = 90) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = self._request(
                "GET",
                f"/api/v1/workspaces/{self.args.workspace_id}/mcp-capabilities",
            ).json()
            if any(
                row.get("capability") == capability and row.get("status") == "ready"
                for row in rows
            ):
                return
            time.sleep(2)
        raise RuntimeError(f"{capability}_not_ready")

    def _poll(
        self, path: str, timeout: int, *, failed_settle_seconds: int = 0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self._request("GET", path).json()
            if last.get("status") in TERMINAL:
                if (
                    last.get("status") != "succeeded"
                    and failed_settle_seconds > 0
                ):
                    first_terminal = (
                        last.get("status"),
                        last.get("error_code"),
                    )
                    settle_deadline = time.monotonic() + failed_settle_seconds
                    while time.monotonic() < settle_deadline:
                        time.sleep(2)
                        current = self._request("GET", path).json()
                        if (
                            current.get("status"),
                            current.get("error_code"),
                        ) != first_terminal:
                            current["_late_terminal_transition"] = True
                            last = current
                            break
                return last
            time.sleep(1)
        raise RuntimeError(f"timed_out:{safe_error_category(last.get('status'), 'unknown')}")

    def _find_runs(
        self,
        *,
        role: str,
        course_id: str | None,
        lesson_id: str | None,
        language: str | None,
        after: datetime,
        before: datetime,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            params: dict[str, Any] = {"role": role, "limit": 50}
            if course_id:
                params["course_id"] = course_id
            runs = self._request(
                "GET",
                f"/api/v1/workspaces/{self.args.workspace_id}/agent-runs",
                params=params,
            ).json()
            matched: list[dict[str, Any]] = []
            for run in runs:
                identity = run.get("identity") or {}
                created_at = parse_time(run["created_at"])
                if created_at < after or created_at > before:
                    continue
                if lesson_id and identity.get("lesson_id") != lesson_id:
                    continue
                if language and identity.get("code_language") != language:
                    continue
                matched.append(
                    self._request(
                        "GET",
                        f"/api/v1/workspaces/{self.args.workspace_id}/agent-runs/{run['id']}",
                    ).json()
                )
            if matched:
                return matched
            time.sleep(1)
        raise RuntimeError("agent_run_missing")

    def _provider_facts(self, runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
        calls: list[dict[str, Any]] = []
        for run in runs:
            calls.extend(
                self._request(
                    "GET",
                    f"/api/v1/workspaces/{self.args.workspace_id}/provider-calls",
                    params={"agent_run_id": run["id"], "limit": 50},
                ).json()
            )
        known_cost = Decimal("0")
        known_count = 0
        unknown_count = 0
        for call in calls:
            cost = call.get("cost") or {}
            if cost.get("status") == "calculated" and cost.get("amount") is not None:
                known_cost += Decimal(cost["amount"])
                known_count += 1
            else:
                unknown_count += 1
        input_values = [c.get("input_tokens") for c in calls]
        output_values = [c.get("output_tokens") for c in calls]
        return {
            "provider_call_count": len(calls),
            "provider_succeeded_count": sum(c.get("status") == "succeeded" for c in calls),
            "provider_failed_count": sum(c.get("status") != "succeeded" for c in calls),
            "repair_count": sum(c.get("phase") == "repair" for c in calls),
            "input_tokens": (
                sum(int(v) for v in input_values if v is not None)
                if any(v is not None for v in input_values)
                else None
            ),
            "output_tokens": (
                sum(int(v) for v in output_values if v is not None)
                if any(v is not None for v in output_values)
                else None
            ),
            "known_cost_cny": (
                format(known_cost, ".8f") if known_count else None
            ),
            "unknown_cost_call_count": unknown_count,
        }

    @staticmethod
    def _tool_facts(
        runs: Iterable[dict[str, Any]], prefixes: Iterable[str]
    ) -> tuple[bool, bool, int]:
        matches = [
            call
            for run in runs
            for call in run.get("tool_calls", [])
            if any(str(call.get("tool_name", "")).startswith(prefix) for prefix in prefixes)
        ]
        return (
            bool(matches),
            any(call.get("status") == "succeeded" for call in matches),
            len(matches),
        )

    @staticmethod
    def _has_duplicate_attempts(runs: Iterable[dict[str, Any]]) -> bool:
        """Detect duplicate execution facts, not legitimate delivery retries."""
        seen: set[tuple[Any, Any]] = set()
        for run in runs:
            key = (run.get("role"), run.get("attempt_number"))
            if key in seen:
                return True
            seen.add(key)
        return False

    @staticmethod
    def _classify(
        *, status: str, error: Any, expectation: str, called: bool, succeeded: bool
    ) -> tuple[str, str]:
        if status != "succeeded":
            return "failed", safe_error_category(error, "business_failed")
        if expectation == "required" and not called:
            return "failed", "tool_call_missed"
        if expectation == "required" and not succeeded:
            return "failed", "tool_call_failed"
        if expectation == "forbidden" and called:
            return "failed", "forbidden_tool_called"
        return "succeeded", "none"

    def ensure_code_policy(self) -> None:
        path = f"/api/v1/workspaces/{self.args.workspace_id}/mcp-policy"
        policy = self._request("GET", path).json()
        self.original_policy = bool(policy.get("code_execution_enabled"))
        if not self.original_policy:
            self._request(
                "PATCH", path, json={"code_execution_enabled": True}
            )

    def restore_code_policy(self) -> None:
        if self.original_policy is False:
            self._request(
                "PATCH",
                f"/api/v1/workspaces/{self.args.workspace_id}/mcp-policy",
                json={"code_execution_enabled": False},
            )

    def run_code_lab(self, language: str) -> None:
        sample_id = f"remote-code-lab-{language}"
        key = f"{sample_id}:1"
        if key in self.completed_keys:
            return
        programs = {
            "python": ("print(input())", "remote-gate"),
            "java": (
                "class Main { public static void main(String[] a) throws Exception "
                "{ System.out.print(new java.io.BufferedReader(new "
                "java.io.InputStreamReader(System.in)).readLine()); } }",
                "remote-gate",
            ),
            "cpp": (
                "#include <iostream>\n#include <string>\nint main(){std::string s;"
                "std::getline(std::cin,s);std::cout<<s;}",
                "remote-gate",
            ),
        }
        source, stdin = programs[language]
        after = utc_now()
        started = time.monotonic()
        created = self._request(
            "POST",
            f"/api/v1/workspaces/{self.args.workspace_id}/code-runs",
            headers={"Idempotency-Key": f"remote-gate-{uuid4()}"},
            json={"language": language, "source_code": source, "stdin": stdin},
        ).json()
        result = self._poll(
            f"/api/v1/workspaces/{self.args.workspace_id}/code-runs/{created['id']}",
            self.args.code_timeout,
        )
        completed = utc_now()
        runs = self._find_runs(
            role="code_execution",
            course_id=None,
            lesson_id=None,
            language=language,
            after=after,
            before=completed,
        )
        latency = int((time.monotonic() - started) * 1000)
        record = self._base_record(
            sample_id=sample_id,
            capability="code_execution",
            repetition=1,
            language=language,
            mode="code_lab",
            item_count=None,
            expectation="required",
            authorized=True,
            latency_ms=latency,
        )
        record["agent_run_count"] = len(runs)
        called, succeeded, count = self._tool_facts(
            runs, ("McpCodeExecution", "CodeExecution", "run_code")
        )
        record["tool_called"] = called or result.get("runtime") is not None
        record["tool_succeeded"] = (
            succeeded or (result.get("status") == "succeeded" and result.get("exit_code") == 0)
        )
        record["mcp_call_count"] = max(count, 1 if record["tool_called"] else 0)
        result_status = (
            "succeeded" if result.get("status") == "completed" else result.get("status", "failed")
        )
        status, category = self._classify(
            status=result_status,
            error=next((run.get("error_code") for run in runs if run.get("error_code")), None),
            expectation="required",
            called=record["tool_called"],
            succeeded=record["tool_succeeded"],
        )
        record["final_status"] = status
        record["failure_category"] = category
        record["business_error_category"] = safe_error_category(
            next((run.get("error_code") for run in runs if run.get("error_code")), None),
            "none",
        )
        if self._has_duplicate_attempts(runs):
            record["final_status"] = "failed"
            record["failure_category"] = "duplicate_agent_runs"
        self._record(key, record)

    def _probe_code_execution(self) -> None:
        """Fail before paid provider calls unless one real C++ run completes."""
        source = (
            "#include <iostream>\n#include <string>\n"
            "int main(){std::string s;std::getline(std::cin,s);std::cout<<s;}"
        )
        created = self._request(
            "POST",
            f"/api/v1/workspaces/{self.args.workspace_id}/code-runs",
            headers={"Idempotency-Key": f"remote-gate-probe-{uuid4()}"},
            json={"language": "cpp", "source_code": source, "stdin": "probe"},
        ).json()
        result = self._poll(
            f"/api/v1/workspaces/{self.args.workspace_id}/code-runs/{created['id']}",
            self.args.code_timeout,
        )
        if result.get("status") != "completed" or result.get("exit_code") != 0:
            raise RuntimeError("code_execution_probe_failed")

    def run_practice(
        self,
        *,
        sample_id: str,
        lesson: LessonRef,
        repetition: int,
        mode: str,
        item_count: int,
        language: str | None,
        expectation: str,
        code_authorized: bool,
        science_authorized: bool,
    ) -> None:
        key = f"{sample_id}:{repetition}"
        if key in self.completed_keys:
            return
        body: dict[str, Any] = {
            "item_count": item_count,
            "difficulty": "standard",
            "output_language": "zh-CN",
            "external_processing_ack": True,
            "item_type_mode": mode,
            "code_tool_authorized": code_authorized,
            "science_tool_authorized": science_authorized,
        }
        if language:
            body["code_languages"] = [language]
        if code_authorized:
            self._wait_capability("code_execution")
        if science_authorized:
            self._wait_capability("science_computation")
        after = utc_now()
        started = time.monotonic()
        create_path = (
            f"/api/v1/workspaces/{self.args.workspace_id}/courses/{lesson.course_id}"
            f"/versions/{lesson.course_version_id}/lessons/{lesson.lesson_id}"
            f"/versions/{lesson.lesson_version_id}/practice-sets"
        )
        created: dict[str, Any] | None = None
        create_error: RemoteHttpError | None = None
        create_idempotency = f"remote-gate-{uuid4()}"
        for _attempt in range(12):
            try:
                created = self._request(
                    "POST",
                    create_path,
                    headers={"Idempotency-Key": create_idempotency},
                    json=body,
                ).json()
                break
            except RemoteHttpError as exc:
                create_error = exc
                if exc.error_code not in {
                    "practice_generation_active",
                    "code_execution_unavailable",
                    "science_computation_unavailable",
                }:
                    break
                time.sleep(2)
        if created is None:
            record = self._base_record(
                sample_id=sample_id,
                capability=(
                    "practice_coding"
                    if mode == "require_coding"
                    else "practice_science"
                    if mode == "require_science"
                    else "practice_general"
                ),
                repetition=repetition,
                language=language,
                mode=mode,
                item_count=item_count,
                expectation=expectation,
                authorized=code_authorized or science_authorized,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            record["business_error_category"] = (
                create_error.error_code if create_error else "request_rejected"
            )
            record["failure_category"] = record["business_error_category"]
            self._record(key, record)
            return
        result = self._poll(
            f"/api/v1/workspaces/{self.args.workspace_id}/practice-jobs/{created['id']}",
            self.args.practice_timeout,
            failed_settle_seconds=self.args.practice_failed_settle_seconds,
        )
        time.sleep(3)
        runs = self._find_runs(
            role="exercise_author",
            course_id=lesson.course_id,
            lesson_id=lesson.lesson_id,
            language=None,
            after=after,
            before=utc_now(),
        )
        record = self._base_record(
            sample_id=sample_id,
            capability=(
                "practice_coding"
                if mode == "require_coding"
                else "practice_science" if mode == "require_science" else "practice_general"
            ),
            repetition=repetition,
            language=language,
            mode=mode,
            item_count=item_count,
            expectation=expectation,
            authorized=code_authorized or science_authorized,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        record["agent_run_count"] = len(runs)
        record.update(self._provider_facts(runs))
        prefixes = (
            ("ValidateCodingReference",)
            if mode == "require_coding"
            else ("VerifyScientificAnswer",) if science_authorized else ()
        )
        called, succeeded, count = self._tool_facts(runs, prefixes)
        verification = result.get("science_verification") or {}
        if mode == "require_science":
            called = called or bool(verification.get("used"))
            succeeded = succeeded or verification.get("status") == "verified"
        record["tool_called"] = called
        record["tool_succeeded"] = succeeded
        record["mcp_call_count"] = count
        if result.get("status") == "succeeded" and result.get("practice_set_id"):
            practice_set = self._request(
                "GET",
                f"/api/v1/workspaces/{self.args.workspace_id}/practice-sets/"
                f"{result['practice_set_id']}",
            ).json()
            record["final_item_count"] = practice_set.get("item_count")
        status, category = self._classify(
            status=result.get("status", "failed"),
            error=result.get("error_code")
            or next((run.get("error_code") for run in runs if run.get("error_code")), None),
            expectation=expectation,
            called=called,
            succeeded=succeeded,
        )
        if (
            status == "succeeded"
            and record["final_item_count"] != item_count
        ):
            status, category = "failed", "item_count_mismatch"
        record["final_status"] = status
        record["failure_category"] = category
        record["business_error_category"] = safe_error_category(
            result.get("error_code")
            or next((run.get("error_code") for run in runs if run.get("error_code")), None),
            "none",
        )
        if self._has_duplicate_attempts(runs):
            record["final_status"] = "failed"
            record["failure_category"] = "duplicate_agent_runs"
        if result.get("_late_terminal_transition"):
            record["final_status"] = "failed"
            record["failure_category"] = "late_terminal_transition"
        self._record(key, record)

    def run_tutor(
        self,
        *,
        sample_id: str,
        lesson: LessonRef,
        repetition: int,
        question: str,
        capability: str,
        expectation: str,
        code_authorized: bool,
        science_authorized: bool,
    ) -> None:
        key = f"{sample_id}:{repetition}"
        if key in self.completed_keys:
            return
        if code_authorized:
            self._wait_capability("code_execution")
        if science_authorized:
            self._wait_capability("science_computation")
        started = time.monotonic()
        session = self._request(
            "POST",
            f"/api/v1/workspaces/{self.args.workspace_id}/courses/"
            f"{lesson.course_id}/tutor-sessions",
            json={
                "course_version_id": lesson.course_version_id,
                "external_processing_ack": True,
            },
        ).json()
        after = utc_now()
        turn_path = (
            f"/api/v1/workspaces/{self.args.workspace_id}/tutor-sessions/"
            f"{session['id']}/turns"
        )
        turn_body = {
            "question": question,
            "scope": "course",
            "code_tool_authorized": code_authorized,
            "science_tool_authorized": science_authorized,
        }
        turn_key = f"remote-gate-{uuid4()}"
        turn: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                turn = self._request(
                    "POST",
                    turn_path,
                    headers={"Idempotency-Key": turn_key},
                    json=turn_body,
                ).json()
                break
            except httpx.TimeoutException:
                if attempt == 2:
                    raise
                time.sleep(2)
        if turn is None:
            raise RuntimeError("tutor_turn_create_failed")
        result = self._poll(
            f"/api/v1/workspaces/{self.args.workspace_id}/tutor-turns/{turn['id']}",
            self.args.tutor_timeout,
            failed_settle_seconds=self.args.tutor_failed_settle_seconds,
        )
        time.sleep(2)
        runs = self._find_runs(
            role="tutor",
            course_id=lesson.course_id,
            lesson_id=None,
            language=None,
            after=after,
            before=utc_now(),
        )
        record = self._base_record(
            sample_id=sample_id,
            capability=capability,
            repetition=repetition,
            language=None,
            mode="tutor",
            item_count=None,
            expectation=expectation,
            authorized=code_authorized or science_authorized,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        record["agent_run_count"] = len(runs)
        record.update(self._provider_facts(runs))
        prefixes = (
            ("McpCodeTool",)
            if capability == "tutor_code"
            else ("McpScienceTool",)
            if capability == "tutor_science"
            else ("McpCodeTool", "McpScienceTool")
        )
        called, succeeded, count = self._tool_facts(runs, prefixes)
        if capability == "tutor_code":
            called = called or bool(result.get("code_tool_used"))
            count = max(count, int(result.get("code_tool_call_count") or 0))
        elif capability == "tutor_science":
            called = called or bool(result.get("science_tool_used"))
            count = max(count, int(result.get("science_tool_call_count") or 0))
        record["tool_called"] = called
        record["tool_succeeded"] = succeeded
        record["mcp_call_count"] = count
        status, category = self._classify(
            status=result.get("status", "failed"),
            error=result.get("error_code")
            or next((run.get("error_code") for run in runs if run.get("error_code")), None),
            expectation=expectation,
            called=called,
            succeeded=succeeded,
        )
        record["final_status"] = status
        record["failure_category"] = category
        record["business_error_category"] = safe_error_category(
            result.get("error_code")
            or next((run.get("error_code") for run in runs if run.get("error_code")), None),
            "none",
        )
        if self._has_duplicate_attempts(runs):
            record["final_status"] = "failed"
            record["failure_category"] = "duplicate_agent_runs"
        if result.get("_late_terminal_transition"):
            record["final_status"] = "failed"
            record["failure_category"] = "late_terminal_transition"
        self._record(key, record)

    def execute(self) -> None:
        self.preflight()
        self.ensure_code_policy()
        sections = set(self.args.section or ("code", "coding", "science", "tutor", "budget"))
        try:
            if "code" in sections:
                for language in ("python", "java", "cpp"):
                    self.run_code_lab(language)
                    record = next(
                        (
                            row
                            for row in reversed(self.records)
                            if row["sample_id"] == f"remote-code-lab-{language}"
                        ),
                        None,
                    )
                    if record is None or record["final_status"] != "succeeded":
                        raise RuntimeError("code_execution_probe_failed")

            algorithm_lessons = self.args.algorithm_lesson
            if "coding" in sections:
                if "code" not in sections:
                    self._probe_code_execution()
                for language in (
                    self.args.coding_language or ("python", "java", "cpp")
                ):
                    for repetition in range(1, self.args.repetitions + 1):
                        lesson = algorithm_lessons[
                            (repetition - 1) % len(algorithm_lessons)
                        ]
                        self.run_practice(
                            sample_id=f"remote-practice-coding-{language}",
                            lesson=lesson,
                            repetition=repetition,
                            mode="require_coding",
                            item_count=1,
                            language=language,
                            expectation="required",
                            code_authorized=True,
                            science_authorized=False,
                        )

            if "science" in sections:
                for repetition in range(1, self.args.repetitions + 1):
                    lesson = self.args.science_lesson[
                        (repetition - 1) % len(self.args.science_lesson)
                    ]
                    self.run_practice(
                        sample_id="remote-practice-science-required",
                        lesson=lesson,
                        repetition=repetition,
                        mode="require_science",
                        item_count=1,
                        language=None,
                        expectation="required",
                        code_authorized=False,
                        science_authorized=True,
                    )

                for repetition in range(1, self.args.negative_repetitions + 1):
                    self.run_practice(
                        sample_id="remote-practice-science-negative",
                        lesson=self.args.concept_lesson,
                        repetition=repetition,
                        mode="general_only",
                        item_count=1,
                        language=None,
                        expectation="forbidden",
                        code_authorized=False,
                        science_authorized=True,
                    )

            if "tutor" in sections:
                for repetition in range(1, self.args.repetitions + 1):
                    self.run_tutor(
                        sample_id="remote-tutor-code-required",
                        lesson=algorithm_lessons[
                            (repetition - 1) % len(algorithm_lessons)
                        ],
                        repetition=repetition,
                        question=(
                            "请实际调用代码执行工具运行一个最小 Java 示例，验证整数溢出"
                            "会怎样影响算法结果，再根据运行观察解释。"
                        ),
                        capability="tutor_code",
                        expectation="required",
                        code_authorized=True,
                        science_authorized=False,
                    )
                    self.run_tutor(
                        sample_id="remote-tutor-wolfram-required",
                        lesson=self.args.science_lesson[
                            (repetition - 1) % len(self.args.science_lesson)
                        ],
                        repetition=repetition,
                        question=(
                            "请实际调用 Wolfram 工具求解方程 x^5-x+1=0 的数值根，"
                            "并基于工具观察说明结果。"
                        ),
                        capability="tutor_science",
                        expectation="required",
                        code_authorized=False,
                        science_authorized=True,
                    )

                for repetition in range(1, self.args.negative_repetitions + 1):
                    self.run_tutor(
                        sample_id="remote-tutor-tools-negative",
                        lesson=self.args.concept_lesson,
                        repetition=repetition,
                        question="请概括这门课程中两种软件开发组织方式的主要差异。",
                        capability="tutor_tools",
                        expectation="forbidden",
                        code_authorized=True,
                        science_authorized=True,
                    )

            if "budget" in sections and self.args.include_budget_curve:
                if "code" not in sections and "coding" not in sections:
                    self._probe_code_execution()
                for count in (1, 3, 5, 10):
                    self.run_practice(
                        sample_id=f"remote-budget-general-{count}",
                        lesson=self.args.concept_lesson,
                        repetition=1,
                        mode="general_only",
                        item_count=count,
                        language=None,
                        expectation="forbidden",
                        code_authorized=False,
                        science_authorized=False,
                    )
                    self.run_practice(
                        sample_id=f"remote-budget-coding-{count}",
                        lesson=algorithm_lessons[0],
                        repetition=1,
                        mode="require_coding",
                        item_count=count,
                        language="java",
                        expectation="required",
                        code_authorized=True,
                        science_authorized=False,
                    )
                    self.run_practice(
                        sample_id=f"remote-budget-science-{count}",
                        lesson=self.args.science_lesson[0],
                        repetition=1,
                        mode="require_science",
                        item_count=count,
                        language=None,
                        expectation="required",
                        code_authorized=False,
                        science_authorized=True,
                    )
        finally:
            self.restore_code_policy()
            self._write()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--api-url", default="http://127.0.0.1:8000")
    result.add_argument("--workspace-id", required=True)
    result.add_argument(
        "--algorithm-lesson", type=LessonRef.parse, action="append", required=True
    )
    result.add_argument(
        "--science-lesson", type=LessonRef.parse, action="append", required=True
    )
    result.add_argument("--concept-lesson", type=LessonRef.parse, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--repetitions", type=int, default=5)
    result.add_argument("--negative-repetitions", type=int, default=3)
    result.add_argument(
        "--coding-language",
        action="append",
        choices=("python", "java", "cpp"),
    )
    result.add_argument("--practice-timeout", type=int, default=720)
    result.add_argument("--tutor-timeout", type=int, default=240)
    result.add_argument("--code-timeout", type=int, default=90)
    result.add_argument("--practice-failed-settle-seconds", type=int, default=200)
    result.add_argument("--tutor-failed-settle-seconds", type=int, default=130)
    result.add_argument("--include-budget-curve", action="store_true")
    result.add_argument(
        "--section",
        action="append",
        choices=("code", "coding", "science", "tutor", "budget"),
    )
    result.add_argument("--resume", action="store_true")
    result.add_argument("--preflight-only", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if len(args.algorithm_lesson) < 2:
        raise SystemExit("at least two algorithm lessons are required")
    if len(args.science_lesson) < 2:
        raise SystemExit("at least two science lessons are required")
    if args.repetitions < 1 or args.negative_repetitions < 0:
        raise SystemExit(
            "required repetitions must be positive and negative repetitions non-negative"
        )
    gate = RemoteGate(args)
    try:
        if args.preflight_only:
            gate.preflight()
            print("REMOTE GATE PREFLIGHT: ready")
            return 0
        gate.execute()
    finally:
        gate.close()
    failures = sum(r["final_status"] != "succeeded" for r in gate.records)
    print(f"REMOTE GATE COMPLETE: records={len(gate.records)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
