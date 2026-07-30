# Slice 2B Durable Remote Tool Fact Review

Date: 2026-07-30

Status: implementation accepted locally; quality optimization remains open

## Decision

Spec 008 and ADR 006 are accepted and implemented. A remote tool attempt now
reserves its authorization budget and writes a `started` `AgentToolCall` in one
independent transaction before the request leaves the process. Success,
failure, and timeout finalization also use independent transactions.

Business rollback no longer restores consumed tool budget or erases the remote
attempt. Local-only progress facts are snapshotted before rollback and restored
only when their `(agent_run_id, ordinal)` is not already represented by a
durable remote fact.

## Integrity Controls

- Authorization consumption uses an atomic conditional update.
- The database rejects negative or over-limit authorization counters.
- The database rejects invalid tool-call status and negative ordinal values.
- Tool calls use a workspace-aware foreign key to their `AgentRun`.
- `(agent_run_id, ordinal)` remains unique.
- Failed reservation never sends the remote request.
- Failure handling rolls back before reading durable facts and never inserts a
  second copy of an already committed remote call.

## Verification

- Focused recorder, migration, and practice-worker tests: `17 passed`.
- Controlled Compose system Gate: `11 passed`.
- Alembic on the development database: `0026 (head)`.
- `git diff --check`: clean.

The controlled C++ compile-failure counterexample also passed after the worker
failure-path correction. It previously reproduced a duplicate ordinal write
when the old rollback-recovery path tried to copy a durable call.

## Low-Cost Real Pilots

Two one-sample pilots were run after a zero-cost remote capability preflight:

- C++ Practice: succeeded, with real provider and Judge0 calls.
- Required-science Practice: failed with
  `scientific_repair_revalidation_failed`, but the report retained
  `tool_called=true` and two Wolfram MCP attempts.

The second result is the key acceptance evidence for Spec 008: a failed
business transaction no longer falsely reports that no science tool was
called. The remaining science failure is a reference/repair quality problem,
not an observability or authorization-accounting failure.

Reports:

- `reviews/remote/slice2b-real-remote-20260730-205534.json`
- `reviews/remote/slice2b-real-remote-20260730-210240.json`

## Remaining Work

- Do not run the full paid denominator yet. One C++ success is not a stable
  success-rate baseline, and it required delivery retries.
- Required-science generation still needs optimization so the generated
  reference and its repair can pass Wolfram equivalence validation.
- Provider rates are not configured for these historical calls, so CNY cost
  remains unknown rather than being reported as a false zero.

These are explicit inputs to Stage 5 Part 3 optimization. They no longer block
the correctness of the Slice 2B fact pipeline.

## OCR Review

The independent review covered two isolated blocks:

- data model, migration, recorder, and focused tests: 6 files, 8 comments;
- Course, Practice, Tutor, and worker integrations: 4 files, 13 comments.

Accepted fixes:

- finalize the running `AgentRun` when a claimed Practice job is canceled;
- finalize durable tool facts when unexpected Course/Practice tool exceptions
  escape;
- distinguish authorization-budget exhaustion from missing authorization;
- make concurrent Course authorization creation idempotent while requiring an
  exact immutable snapshot match;
- reject whitespace-only tool names;
- narrow the Postgres foreign-key counterexample to `IntegrityError`;
- quote throwaway Postgres database identifiers.

Rejected or deferred findings:

- Migration 0026 does not recreate `uq_agent_tool_calls_ordinal` because
  migration 0010 already owns that constraint. The real 0025 -> 0026 ->
  0025 round trip verifies its presence.
- The local Postgres test credentials are documented development defaults, not
  production secrets. They remain overridable at the environment boundary used
  by the repository.
- `Session.identity_map` and `Session.new` are public SQLAlchemy Session
  collections used only to preserve unflushed local progress before rollback;
  replacing them would not improve the transaction contract.
- A hypothetical failure while `_fail_job` itself flushes cannot be converted
  into a truthful successful finalization in the same failed database
  transaction. It must remain visible as a database failure.
- Small helper-duplication and dead-code comments were addressed where safe but
  were not allowed to expand into unrelated refactoring.

Post-fix verification:

- focused recorder, migration, worker, provider-chain, and tool-funnel tests:
  `67 passed`;
- controlled Compose system Gate: `11 passed`;
- `git diff --check`: clean.
