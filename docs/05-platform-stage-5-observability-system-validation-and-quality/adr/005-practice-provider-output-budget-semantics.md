# ADR 005: Practice provider output budget semantics

Date: 2026-07-30

Status: Accepted as a narrow real-Gate remediation

## Context

Practice generation sent `practice_generation_max_output_tokens` to every
provider request, but also reused the same value as a cumulative limit across
the complete attempt. A plan, initial generation and one repair could therefore
all finish below their individual provider limit and still be rejected after
the repair response had already been generated and billed.

The accepted Practice contract already bounds an attempt by provider calls,
steps, searches, tool calls and wall time. The cumulative check neither stopped
the paid request nor reduced its cost; it discarded an already-paid result.

## Decision

- `practice_generation_max_output_tokens` and
  `practice_grading_max_output_tokens` are per-provider-call limits.
- `finish_reason=length`, or one response exceeding its own requested limit,
  remains a stable budget failure.
- Attempt-wide bounds remain the existing provider-call, step, tool and wall
  limits. This decision does not raise those limits.
- Provider usage continues to record actual cumulative input/output tokens for
  observability and cost reporting.

## Consequences

Repair output is no longer rejected solely because earlier successful calls
used tokens. The maximum number of paid calls is unchanged. Focused tests must
prove both that cumulative output may exceed one call's ceiling and that a
single oversized/length-truncated response still fails with zero half-finished
Practice Set.
