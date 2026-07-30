# Slice 2A OCR Review

## Background

Stage 5 Part 2 Slice 2A adds durable Provider Call facts across business rollback,
controlled Tutor system tests, four-chain Postgres orchestration evidence, Playwright
Tutor smoke, and CI gates. OCR supplements Codex self-review and executed system/browser
validation; it does not replace either.

## Scope And Execution

The review used repository-external, allowlisted Git copies. It excluded `.env`, provider
configuration, uploaded material, logs, generated browser artifacts, `.tmp/`, `artifacts/`,
and unrelated product code.

Each block used:

```text
ocr review --audience human --concurrency 1 --timeout 10 --background "<block context>"
```

Reviewed blocks:

| Block | Files | OCR comments |
|---|---:|---:|
| Durable recorder | 1 | 5 |
| Tutor write path | 1 | 4 |
| Course and RAG write paths | 2 | 12 |
| Practice write path | 1 | 7 |
| Acceptance tests | 7 | 26 |
| Controlled system harness | 7 | 10 |
| Browser and CI | 6 | 13 |

All seven final blocks produced a complete Summary. The original combined write-path
attempt ended after an OCR internal invalid line-range request and was not counted as a
completed review. No residual OCR process remained before the split rerun.

Raw output is archived under:

`reviews/raw/slice2a_20260729_v2/`

## Accepted Findings

Six narrow test and CI findings were accepted:

1. The POSIX browser runner changed directory before its EXIT cleanup trap.
2. The model-service stub split active-scenario selection and call-count increment across
   two lock acquisitions.
3. Tutor repair system evidence did not assert non-empty answer blocks.
4. The Course provider-failure orchestration test accepted any `ValueError`.
5. A rate-snapshot test used a fixed future date that would expire.
6. Playwright course-response diagnostics were weaker than Reader diagnostics and its
   dialog acceptance returned an unobserved promise.

The fixes are limited to:

- `scripts/browser-test.sh`
- `tests/system/model_services_stub/server.py`
- `tests/system/test_tutor_vertical.py`
- `apps/api/tests/test_four_chain_orchestration_postgres.py`
- `apps/api/tests/test_provider_call_recorder.py`
- `apps/web/e2e/app-shell.spec.ts`

No product code changed during the OCR-fix task.

## Rejected Or Deferred Findings

- Claims that GitHub Actions v6 tags do not exist were based on stale tool knowledge.
- `scripts/system-test.sh` and the Redis healthcheck exist in the full repository; their
  absence was caused by isolated review blocks.
- Final business commits remain worker/caller responsibilities. Real Postgres tests lock
  the resulting terminal state; no service-level commit contract was changed.
- Fixed credentials belong only to an isolated disposable Postgres service and are not
  production secrets.
- Recorder ordinal concurrency, test-session-factory cleanup, N+1 cleanup, Java harness
  flexibility, unused imports, and broader provider-failure coverage are not Slice 2A
  OCR blockers. Relevant behavioral risks may be reconsidered in Slice 2B or final
  optimization without mixing them into this correction.

## Verification

GLM reported:

- Recorder and four-chain focused tests: `73 passed`
- Tutor controlled system tests: `3 passed` covering success, repair, and timeout
- Full Tutor Playwright flow: `1 passed`
- Web lint: zero errors
- Web build: passed
- `git diff --check`: passed

Codex independently inspected all six correction diffs and reran `git diff --check`.
The POSIX script correction is structurally limited to a subshell that preserves the
repository-root cleanup directory. A local Bash syntax-only check could not run because
the Windows WSL service denied instance creation; the script was therefore not claimed
as independently executed on Linux in this review.

## Conclusion

Slice 2A OCR is accepted after the six narrow corrections. No further OCR rerun is
required because the fixes are small, directly correspond to the reviewed findings, and
were covered by focused system/browser verification.
