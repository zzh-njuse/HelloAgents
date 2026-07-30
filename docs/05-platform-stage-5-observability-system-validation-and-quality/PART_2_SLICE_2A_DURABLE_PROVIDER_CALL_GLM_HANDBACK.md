# Stage 5 Part 2 Slice 2A：Provider Call 持久化修复 — GLM Handback

状态：四链 Orchestration 验收修正完成

日期：2026-07-29

## 1. 修改文件

| 文件 | 变更 |
|---|---|
| `apps/api/tests/test_provider_call_recorder.py` | 删除 2 个手工 Trace 测试、6 个直接 finalizer 测试、2 个直接 recorder.start() FK 测试、1 个重复无效 phase 测试；保留 finalizer 单元测试但改为准确名称；新增 1 个输入校验测试 |
| `apps/api/tests/test_provider_call_chain_behavior.py` | 删除 1 个手工复制 Course owner/authorization 顺序的测试 |
| `apps/api/tests/test_acceptance_evidence_rag_trace.py` | **新增**：3 个通过真实 `answer_question()` 的 RAG Trace 验收测试 |
| `apps/api/tests/test_acceptance_evidence_course_owner.py` | **新增**：2 个通过真实 `_execute_lesson_generation()` 的 Course owner 验收测试 |
| `apps/api/tests/test_acceptance_evidence_wrapper.py` | **新增**：5 个通过真实 `record_provider_call()` 的 FK 失败和 wrapper 最终化验收测试 |
| `apps/api/tests/test_four_chain_orchestration_postgres.py` | **新增**：11 个四链 Postgres orchestration 测试（Course generation normal/repair、Practice generation normal/repair、Practice grading normal/repair、RAG Answer normal/repair/timeout、owner 互斥、Course timeout） |
| `docs/.../PART_2_SLICE_2A_DURABLE_PROVIDER_CALL_GLM_HANDBACK.md` | 更新 handback |

**产品代码零修改确认**：未修改任何 `apps/api/learn_platform_api/**` 文件。

## 2. 被删除或重写的无效测试

| 旧测试名 | 无效原因 | 替代 |
|---|---|---|
| `test_rag_trace_succeeded_is_committed` | 手工创建 Trace、赋值 status、commit；从未调用 `answer_question()` | `test_rag_trace_succeeded_via_answer_question` |
| `test_rag_trace_failed_is_committed` | 同上 | `test_rag_trace_failed_via_answer_question` |
| `test_succeed_raises_on_missing_record` | 直接调用 `recorder.succeed()`，不经过 `record_provider_call()` | `test_recorder_succeed_unit_raises_on_missing_record`（单元测试，保留但改名）+ `test_wrapper_success_finalize_missing_via_record_provider_call`（验收测试） |
| `test_fail_raises_on_missing_record` | 同上 | `test_recorder_fail_unit_raises_on_missing_record` + `test_wrapper_failure_finalize_missing_via_record_provider_call` |
| `test_timeout_raises_on_missing_record` | 同上 | `test_recorder_timeout_unit_raises_on_missing_record` + `test_wrapper_timeout_finalize_missing_via_record_provider_call` |
| `test_cancel_raises_on_missing_record` | 同上 | `test_recorder_cancel_unit_raises_on_missing_record` |
| `test_finalize_missing_does_not_swallow_provider_exception` | 直接调用 `recorder.fail()`，不经过 `record_provider_call()` | `test_wrapper_failure_finalize_missing_via_record_provider_call` |
| `test_record_provider_call_success_finalize_missing_does_not_return_success` | 直接调用 `recorder.succeed()`，不经过 `record_provider_call()` | `test_wrapper_success_finalize_missing_via_record_provider_call` |
| `test_start_fk_failure_nonexistent_agent_run_prevents_provider_call` | 直接调用 `ProviderCallRecorder.start()`；定义了 `fake_call` 但从未传给 wrapper | `test_fk_failure_nonexistent_agent_run_via_wrapper` |
| `test_start_fk_failure_nonexistent_rag_trace_prevents_provider_call` | 同上 | `test_fk_failure_nonexistent_rag_trace_via_wrapper` |
| `test_invalid_phase_prevents_provider_call_renamed` | 与 `test_invalid_phase_rejected_before_provider_call` 和 `test_start_invalid_phase_prevents_provider_call` 重复 | `test_invalid_phase_rejected_is_input_validation`（准确名称） |
| `test_course_lesson_owner_commit_is_minimal` | 在测试中手工复制产品的 create-AgentRun/commit/create-authorization/rollback 顺序 | `test_course_lesson_owner_commit_via_real_service` + `test_course_lesson_owner_commit_antiexample_via_real_service` |

## 3. 每个新测试实际经过的产品入口

### test_acceptance_evidence_rag_trace.py

| 测试 | 经过的产品入口 | monkeypatch 边界 |
|---|---|---|
| `test_rag_trace_succeeded_via_answer_question` | `answer_question()` → `retrieve()` → `record_provider_call()` → `_generate()` | `learn_platform_api.services.answers.retrieve`、`learn_platform_api.services.answers.httpx.post` |
| `test_rag_trace_failed_via_answer_question` | `answer_question()` → `retrieve()` → `record_provider_call()` → `_generate()` (timeout) | 同上 |
| `test_rag_trace_failed_provider_unavailable_via_answer_question` | `answer_question()` → `retrieve()` → `record_provider_call()` → `_generate()` (connect error) | 同上 |

### test_acceptance_evidence_course_owner.py

| 测试 | 经过的产品入口 | monkeypatch 边界 |
|---|---|---|
| `test_course_lesson_owner_commit_via_real_service` | `_execute_lesson_generation()` → `AgentRun` 创建/commit → `JobToolAuthorization` 创建/flush → `_recorded_call_provider()` (失败) | `learn_platform_api.services.course_generation._recorded_call_provider`、`learn_platform_api.services.readiness._read_capability_projection` |
| `test_course_lesson_owner_commit_antiexample_via_real_service` | 同上（反例：若 Fix 3 被回退则 auth_count==1） | 同上 |

### test_acceptance_evidence_wrapper.py

| 测试 | 经过的产品入口 | monkeypatch 边界 |
|---|---|---|
| `test_fk_failure_nonexistent_agent_run_via_wrapper` | `record_provider_call(..., call_fn=fake_call)` → `ProviderCallRecorder.start()` → IntegrityError | FK-enforcing SQLite engine |
| `test_fk_failure_nonexistent_rag_trace_via_wrapper` | 同上（RAG trace FK） | 同上 |
| `test_wrapper_success_finalize_missing_via_record_provider_call` | `record_provider_call(..., call_fn=...)` → `call_fn` 删除记录 → `succeed()` 抛出 RuntimeError | `call_fn` 内使用独立 Session 删除记录 |
| `test_wrapper_failure_finalize_missing_via_record_provider_call` | `record_provider_call(..., call_fn=...)` → `call_fn` 删除记录并抛出 ValueError → `fail()` 抛出 RuntimeError → 原始异常保留 | 同上 |
| `test_wrapper_timeout_finalize_missing_via_record_provider_call` | `record_provider_call(..., call_fn=...)` → `call_fn` 删除记录并抛出 TimeoutException → `timeout()` 抛出 RuntimeError → 原始异常保留 | 同上 |

## 4. monkeypatch 只发生在哪个低层外部边界

| 测试文件 | monkeypatch 目标 | 层级 |
|---|---|---|
| `test_acceptance_evidence_rag_trace.py` | `answers.retrieve`、`answers.httpx.post` | 检索和 provider HTTP |
| `test_acceptance_evidence_course_owner.py` | `course_generation._recorded_call_provider`、`readiness._read_capability_projection` | provider HTTP 和能力投影 |
| `test_acceptance_evidence_wrapper.py` | 无 monkeypatch（使用 FK-enforcing SQLite engine 和 `call_fn` 内删除） | 数据库连接层 |

## 5. 真实执行命令和结果

### 5.1 新增验收测试

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_acceptance_evidence_rag_trace.py `
  apps/api/tests/test_acceptance_evidence_course_owner.py `
  apps/api/tests/test_acceptance_evidence_wrapper.py
```

**结果：10 passed in 18.11s**

### 5.2 Focused recorder + chain behavior tests（含验收测试）

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_provider_call_chain_behavior.py `
  apps/api/tests/test_acceptance_evidence_rag_trace.py `
  apps/api/tests/test_acceptance_evidence_course_owner.py `
  apps/api/tests/test_acceptance_evidence_wrapper.py
```

**结果：104 passed in 142.70s**

包含：
- 62 项 recorder 测试（含 4 项改名后的 finalizer 单元测试、1 项输入校验测试）
- 32 项 chain behavior 测试（删除了 1 个手工复制测试）
- 3 项 RAG Trace 验收测试
- 2 项 Course owner 验收测试
- 5 项 wrapper FK/最终化验收测试

### 5.3 Whitespace check

```powershell
git diff --check
```

**结果：无错误**

## 6. 产品代码零修改确认

- ✅ 未修改任何 `apps/api/learn_platform_api/**` 文件
- ✅ 未修改 migration、ORM schema、Web、Compose、`tests/system/`、CI、Playwright
- ✅ 未修改 fixture 的全局产品语义和依赖

## 7. 未 commit、未 push、未运行 OCR 的确认

- ✅ 未 commit
- ✅ 未 push
- ✅ 未运行 OCR
- ✅ 不安装依赖，不调用真实 provider
- ✅ 不读取或修改 `.tmp/`、`artifacts/`

## 8. 保留的 finalizer 单元测试（改名后）

以下测试保留为 `ProviderCallRecorder` 的单元测试，名称已改为准确描述：

- `test_recorder_succeed_unit_raises_on_missing_record`
- `test_recorder_fail_unit_raises_on_missing_record`
- `test_recorder_timeout_unit_raises_on_missing_record`
- `test_recorder_cancel_unit_raises_on_missing_record`

这些测试直接调用 finalizer 方法，验证 `RuntimeError("provider_call_finalize_missing")`
行为。它们不声称测试 `record_provider_call()` wrapper 行为。

## 9. 四链 Postgres Orchestration 验收修正

### 9.1 修改文件

`apps/api/tests/test_four_chain_orchestration_postgres.py`

### 9.2 删除的异常吞噬

以下 `try/except Exception` + `db.rollback()` 模式已从 normal/repair 测试中删除：

| 测试 | 旧模式 | 修正 |
|---|---|---|
| `test_course_generation_orchestration` | `try: execute_generation(...) except Exception: pg_db.rollback()` | 直接调用 `execute_generation()`，异常直接传播 |
| `test_practice_generation_orchestration` | `try: execute_generation(...) except Exception: pg_db.rollback()` | 直接调用 `execute_generation()`，异常直接传播 |
| `test_practice_grading_orchestration` | `try: execute_grading(...) except Exception: pg_db.rollback()` | 直接调用 `execute_grading()`，异常直接传播 |

RAG Answer 测试继续要求正常返回 `succeeded`（`answer_question()` 本身提交，不吞异常）。
timeout 测试继续使用 `pytest.raises` 预期异常。

### 9.3 锁定的业务最终状态

每条 normal/repair 测试从新 Postgres Session 查询并断言：

| 链 | 场景 | AgentRun/Trace 状态 | Job/Attempt 状态 | 关键业务 artifact |
|---|---|---|---|---|
| Course generation | normal/repair | `AgentRun.status == "succeeded"` | `CourseGenerationJob.status == "succeeded"` | `course_version_id is not None` |
| Practice generation | normal/repair | `AgentRun.status == "succeeded"` | `PracticeJob.status == "succeeded"` | `practice_set_id is not None` |
| Practice grading | normal/repair | `AgentRun.status == "succeeded"` | `PracticeJob.status == "succeeded"`, `PracticeAttempt.status == "succeeded"` | PracticeFeedback 存在 |
| RAG Answer | normal/repair | `RagAnswerTrace.status == "succeeded"` | N/A | `answer_hash` 已填充（由 `answer_question()` 内部 commit） |

Worker 合同：Course/Practice/Grading 的 service 设置状态但不 commit；测试在 service 返回后执行 `pg_db.commit()`，模拟 worker commit。RAG Answer 的 `answer_question()` 内部 commit，无需额外 commit。

### 9.4 精确调用次数与 phase

每个 normal/repair 测试同时断言：
- provider stub/mock 的实际 `call_count`（精确值）
- ProviderCall 精确数量（精确值）
- 两者完全相等
- 精确 phase 序列
- ordinal 精确为 `range(expected_count)`

| 链 | 场景 | mock call_count | ProviderCall count | phase 序列 | ordinal |
|---|---|---|---|---|---|
| Course generation | normal | 2 | 2 | plan → generation | 0, 1 |
| Course generation | repair | 3 | 3 | plan → generation → repair | 0, 1, 2 |
| Practice generation | normal | 2 | 2 | plan → generation | 0, 1 |
| Practice generation | repair | 3 | 3 | plan → generation → repair | 0, 1, 2 |
| Practice grading | normal | 1 | 1 | grading | 0 |
| Practice grading | repair | 2 | 2 | grading → repair | 0, 1 |
| RAG Answer | normal | 1 | 1 | answer | 0 |
| RAG Answer | repair | 2 | 2 | answer → repair | 0, 1 |

timeout 测试精确断言：
- RAG timeout：mock call_count = 1，ProviderCall count = 1，status = timed_out，error_code = provider_timeout
- Course timeout：mock call_count = 1，ProviderCall count = 1，status = timed_out，error_code = provider_timeout

### 9.5 Postgres Gate 修正

- 删除了 `pytest.importorskip("psycopg")`，改为直接 `import psycopg`
- psycopg 缺失时以正常 `ImportError` 失败
- Postgres 不可达时以明确 `RuntimeError` 失败
- 不允许 skip 或 SQLite fallback
- 随机 throwaway database 和 finally 清理保持不变

### 9.6 每条链使用的真实入口

| 链 | 真实入口 | monkeypatch 最低层外部边界 |
|---|---|---|
| Course generation | `execute_generation()` | `course_generation.httpx.post`、`course_generation.retrieve` |
| Practice generation | `execute_generation()` | `practice_generation.call_practice_provider`、`practice_generation.retrieve`、`readiness._read_capability_projection`、`practice_generation._sources` |
| Practice grading | `execute_grading()` | `practice_generation.call_provider` |
| RAG Answer | `answer_question()` | `answers.retrieve`、`answers.httpx.post` |

### 9.7 测试清单

| # | 测试名 | 场景 | phase 序列 | mock call_count | ProviderCall count | owner |
|---|---|---|---|---|---|---|
| 1 | `test_course_generation_orchestration[normal]` | normal | plan → generation | 2 | 2 | AgentRun (course_outline) |
| 2 | `test_course_generation_orchestration[repair]` | repair | plan → generation → repair | 3 | 3 | AgentRun |
| 3 | `test_practice_generation_orchestration[normal]` | normal | plan → generation | 2 | 2 | AgentRun (exercise_author) |
| 4 | `test_practice_generation_orchestration[repair]` | repair | plan → generation → repair | 3 | 3 | AgentRun |
| 5 | `test_practice_grading_orchestration[normal]` | normal | grading | 1 | 1 | AgentRun (answer_grader) |
| 6 | `test_practice_grading_orchestration[repair]` | repair | grading → repair | 2 | 2 | AgentRun |
| 7 | `test_rag_answer_orchestration[normal]` | normal | answer | 1 | 1 | RagAnswerTrace |
| 8 | `test_rag_answer_orchestration[repair]` | repair | answer → repair | 2 | 2 | RagAnswerTrace |
| 9 | `test_rag_answer_timeout_orchestration` | timeout | answer (timed_out) | 1 | 1 | RagAnswerTrace |
| 10 | `test_owner_mutual_exclusion_across_chains` | 互斥 | Course plan+gen, RAG answer | 3 | 3 | 混合 |
| 11 | `test_course_generation_provider_failure_orchestration` | timeout | plan (timed_out) | 1 | 1 | AgentRun |

### 9.8 每个场景的共同断言

- `ProviderCall.workspace_id` 等于业务 Workspace
- owner 正确：Course/Practice 绑定 `agent_run_id`，RAG 绑定 `rag_answer_trace_id`
- owner 互斥：不存在同时设置 `agent_run_id` 和 `rag_answer_trace_id` 的行
- ordinal 从 0 开始、单调递增、无重复（精确 `range(expected_count)`）
- phase 序列与真实 outbound attempt 一致
- mock call_count == ProviderCall count == expected_count（精确，非 `>=`）
- provider/model 来自实际测试配置（`deepseek` / `deepseek-v4-flash`）
- usage（input_tokens, output_tokens）只取 stub 明确报告值
- timeout 场景：`status == "timed_out"`，`error_code == "provider_timeout"`
- 业务 Run/Trace/Job/Attempt 使用既有稳定成功状态
- ProviderCall 表不存在 prompt、回答、用户答案、异常正文、key、内部 URL 或绝对路径字段

### 9.9 Postgres Gate

- 使用随机 throwaway 数据库：`slice2a_4chain_<uuid12>`
- 执行真实 `Base.metadata.create_all()` schema 初始化
- psycopg 缺失时 `ImportError`，Postgres 不可达时 `RuntimeError`，均不 skip
- 测试结束删除临时数据库
- 所有最终证据从 NEW Postgres Session 查询

### 9.10 实际命令与逐项结果

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -v apps/api/tests/test_four_chain_orchestration_postgres.py
```

**结果：11 passed in 27.67s**

逐项：
- `test_course_generation_orchestration[normal]` PASSED
- `test_course_generation_orchestration[repair]` PASSED
- `test_practice_generation_orchestration[normal]` PASSED
- `test_practice_generation_orchestration[repair]` PASSED
- `test_practice_grading_orchestration[normal]` PASSED
- `test_practice_grading_orchestration[repair]` PASSED
- `test_rag_answer_orchestration[normal]` PASSED
- `test_rag_answer_orchestration[repair]` PASSED
- `test_rag_answer_timeout_orchestration` PASSED
- `test_owner_mutual_exclusion_across_chains` PASSED
- `test_course_generation_provider_failure_orchestration` PASSED

### 9.11 Focused regression

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_chain_behavior.py `
  apps/api/tests/test_acceptance_evidence_rag_trace.py `
  apps/api/tests/test_acceptance_evidence_course_owner.py `
  apps/api/tests/test_acceptance_evidence_wrapper.py
```

**结果：42 passed in 83.96s**

### 9.12 Whitespace check

```powershell
git diff --check
```

**结果：无错误**

### 9.13 产品代码零修改确认

- ✅ 未修改任何 `apps/api/learn_platform_api/**` 文件
- ✅ 未修改 migration、ORM schema、Web、Compose、`tests/system/`、CI、Playwright

### 9.14 未 commit、未 push、未运行 OCR 的确认

- ✅ 未 commit
- ✅ 未 push
- ✅ 未运行 OCR
- ✅ 不安装依赖，不调用真实 provider

## 10. 已知风险或合同冲突

无新增风险。本轮只修改测试，不修改产品代码。
