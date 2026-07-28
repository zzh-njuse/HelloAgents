"""Stage 5 Slice 1C — Shared agent-run identity kind precedence (Fix 4).

Single source of truth for owner FK → identity kind mapping. Both the Python
_identity() in agent_runs.py and the SQL CASE in quality_cost.py must read
from this module. The list order defines the priority: first match wins.

This module imports nothing from the ORM or other services, so it can be
imported by both agent_runs.py and quality_cost.py without circular deps.
"""
from __future__ import annotations


# Owner FK column name → identity kind, in precedence order (first match wins).
OWNER_KIND_PRECEDENCE: list[tuple[str, str]] = [
    ("course_generation_job_id", "course_generation"),
    ("tutor_turn_id", "tutor"),
    ("practice_job_id", "practice"),
    ("code_lab_job_id", "code_execution"),
]

# All valid business type values (for validation / SQL ELSE clause)
BUSINESS_TYPES = tuple(kind for _, kind in OWNER_KIND_PRECEDENCE) + ("unknown",)


def owner_kind_from_run(run: object) -> str:
    """Derive identity kind from an AgentRun using the shared precedence.

    Reads owner FK columns in precedence order; first non-null wins.
    Returns 'unknown' if no owner FK is set.
    """
    for col, kind in OWNER_KIND_PRECEDENCE:
        if getattr(run, col, None) is not None:
            return kind
    return "unknown"
