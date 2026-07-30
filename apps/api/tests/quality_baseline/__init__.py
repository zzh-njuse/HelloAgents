"""Stage 5 Part 2 Slice 2B Batch A — high-risk tool & practice quality baseline.

This package is test-only. It establishes reproducible, secret-free, zero-paid-cost
baselines for the four risk axes accepted in Spec 007 (Java/C++ coding practice,
Python control, the Practice Wolfram call funnel, the Tutor code/Wolfram dual-MCP
funnel, and the 1/3/5/10 total-item-count budget curve).

Hard rules honoured by every module here (Slice 2B GLM packet §4 / §10 / Spec 007):

- No ``apps/api/learn_platform_api/**`` product code is modified.
- Every test drives the REAL business orchestration entry point
  (``execute_generation`` / ``execute_grading`` / ``execute_tutor_turn``) and only
  monkeypatches the lowest-level external boundaries: provider HTTP, retrieval,
  the execution-MCP backend, the science-tool MCP, and capability projection.
- Final evidence is always queried from a NEW Postgres Session — never from the
  business session, never from SQLite, never from mock call counts alone.
- When the Postgres Gate is unreachable or a dependency is missing the Gate FAILS;
  it never skips and never falls back to SQLite.
- Controlled/fake backends are marked ``controlled_backend``; nothing here is ever
  reported as a real Judge0 / Wolfram Cloud pass.
- Reports serialize only allowlisted aggregation fields and stable categories;
  prompt, lesson source, stem, answer, code, tests, compiler/Wolfram raw text,
  keys, URLs and absolute paths are never persisted.
"""
