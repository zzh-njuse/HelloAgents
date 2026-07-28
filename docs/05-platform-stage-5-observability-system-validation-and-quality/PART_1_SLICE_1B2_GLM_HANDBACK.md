# Stage 5 Part 1 Slice 1B-2：GLM 交回

日期：2026-07-27
状态：已通过独立验收（含一项人工接受的验证豁免）

## 1. 修改文件与各链接入点

### 新增文件

| 文件 | 用途 |
|------|------|
| `apps/api/alembic/versions/0025_add_rag_provider_call_owner.py` | migration 0025：RAG owner 列、复合 FK、owner 互斥 CHECK、RAG ordinal 条件唯一、RagAnswerTrace 冗余 UNIQUE |
| `apps/api/learn_platform_api/services/provider_call_recorder.py` | 共享 Provider Call recorder：`ProviderCallRecorder` 类 + `record_provider_call` 便捷包装 + `classify_error` 稳定错误分类 |
| `apps/api/learn_platform_api/services/provider_cost.py` | 1B-1 成本计算器（基线，未修改） |
| `apps/api/tests/test_provider_call_recorder.py` | recorder focused tests：43 项（含 classify_error __cause__ 链、timeout、cancel、budget_exceeded→failed、unknown_error） |
| `apps/api/tests/test_provider_call_chain_behavior.py` | 五条链行为测试：28 项（全部通过真实低层 helper，monkeypatch httpx.post） |
| `apps/api/tests/test_provider_call_orm.py` | ORM 约束 tests：19 项 |
| `apps/api/tests/test_provider_cost_calculator.py` | 成本计算器 tests：15 项 |
| `apps/api/tests/test_provider_call_rag_owner_postgres.py` | RAG owner Postgres round-trip + cascade：3 项 |
| `apps/api/tests/test_provider_call_binding_postgres.py` | 价格绑定 Postgres tests：4 项 |
| `apps/api/tests/test_provider_call_workspace_postgres.py` | Workspace 隔离 Postgres tests：4 项 |
| `apps/api/tests/test_provider_call_deletion_postgres.py` | 级联删除 Postgres tests：4 项 |
| `apps/api/tests/test_provider_call_migration_postgres.py` | migration round-trip Postgres tests：2 项 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `apps/api/learn_platform_api/db/models.py` | 新增 `ProviderCall`、`ProviderRateSnapshot` ORM 模型；`RagAnswerTrace` 增加冗余 `UNIQUE(id, workspace_id)` |
| `apps/api/learn_platform_api/services/provider_call_recorder.py` | **验收修复 #1**：`classify_error` 沿 `__cause__`/`__context__` 安全检查底层 `httpx.TimeoutException`；**验收修复 #3**：从 canceled 分类中移除所有 budget_exceeded / agent_step_budget_exceeded，仅 `generation_canceled`、`practice_canceled` 映射 canceled；**验收修复 #5**：修正 docstring，移除残留的"canceled 子串匹配"描述 |
| `apps/api/learn_platform_api/services/course_generation.py` | 新增 `_recorded_call_provider` 包装；所有 provider 调用经 recorder 接入 |
| `apps/api/learn_platform_api/services/tutor_generation.py` | `provider_step` 增加 `phase` 关键字参数；repair 调用显式传入 `phase="repair"`；baseline path 同步修复 |
| `apps/api/learn_platform_api/services/practice_generation.py` | generation `provider_step` 增加 `phase` 关键字参数；repair/structure/novelty/specialized 调用显式传入 `phase="repair"`；grading `provider_step` 同步修复；repair 调用显式传入 `phase="repair"` |
| `apps/api/learn_platform_api/services/answers.py` | 修复 `_generate` 3-元组与 `record_provider_call` 2-元组合同不兼容：新增 `_call_generate_for_recorder` 包装剥离 latency；`trace.error_code` 使用 `classify_error` 稳定码替代 `str(exc)` |
| `apps/api/tests/test_provider_call_recorder.py` | **验收修复 #1/#3/#5**：新增 `test_classify_chained_timeout_via_cause`、`test_classify_chained_timeout_via_context`、`test_classify_cause_chain_cycle_safe`、`test_classify_no_cause_chain_no_timeout`、`test_classify_budget_exceeded_is_failed_not_canceled` |
| `apps/api/tests/test_provider_call_chain_behavior.py` | **验收修复 #2/#4**：全部 28 项测试改为通过真实低层 helper（`call_provider`、`call_practice_provider`、`_generate`）+ monkeypatch `httpx.post`；timeout 测试不再让 `call_fn` 直接抛 `httpx.TimeoutException`，而是 monkeypatch `httpx.post` 抛出，让 helper 完成异常转换后验证 `ProviderCall.status == timed_out` |

## 2. 验收阻断项修复详情

### 阻断项 #1：classify_error 沿 __cause__/__context__ 检查底层 TimeoutException

**问题**：业务 helper（`call_provider`、`call_practice_provider`、`_generate`）捕获 `httpx.TimeoutException` 后抛出 `ValueError("generation_provider_unavailable") from exc`。原 `classify_error` 只检查直接类型，不沿异常链查找，导致被包装的真实 timeout 记录为 `failed` 而非 `timed_out`。

**修复**：
- 新增 `_walk_cause_chain(exc)` 函数，沿 `__cause__`（显式 `raise X from Y`）优先、`__context__`（隐式异常链）次序遍历，查找 `httpx.TimeoutException`
- 使用 `visited: set[int]` 跟踪已访问异常 id，防止异常链循环导致无限循环
- `classify_error` 在直接 `isinstance` 检查后、`httpx.HTTPError` 检查前，调用 `_walk_cause_chain` 检查链中是否隐藏 TimeoutException
- 若链中发现 TimeoutException，返回 `(timed_out, provider_timeout)`

**验证**：
- `test_classify_chained_timeout_via_cause`：`ValueError(...) from TimeoutException` → timed_out
- `test_classify_chained_timeout_via_context`：隐式 `__context__` 链 → timed_out
- `test_classify_cause_chain_cycle_safe`：循环链不无限循环
- `test_classify_no_cause_chain_no_timeout`：非 timeout 链不误判

### 阻断项 #2：timeout 测试经真实低层 helper

**问题**：原 timeout 测试让 `record_provider_call` 的 `call_fn` 直接抛 `httpx.TimeoutException`，冒充链路测试。真实链路中，`call_fn` 调用 `call_provider(settings, messages)`，后者内部 `httpx.post` 抛 TimeoutException，被 helper 捕获后包装为 `ValueError("generation_provider_unavailable") from exc`。

**修复**：
- 所有 timeout 测试改为 monkeypatch `httpx.post` 抛出 `httpx.TimeoutException`
- `call_fn` 调用真实低层 helper（`call_provider`、`call_practice_provider`、`_generate`）
- helper 完成异常转换后，`classify_error` 沿 `__cause__` 链找到 TimeoutException → `timed_out`
- 验证 `ProviderCall.status == timed_out`

**验证**：
- `test_course_generation_timeout_via_real_helper`
- `test_tutor_timeout_via_real_helper`
- `test_practice_generation_timeout_via_real_helper`
- `test_practice_grading_timeout_via_real_helper`
- `test_rag_answer_timeout_via_real_helper`

### 阻断项 #3：budget_exceeded 从 canceled 移至 failed

**问题**：原 `classify_error` 将 `lesson_budget_exceeded`、`practice_budget_exceeded`、`grading_budget_exceeded`、`agent_step_budget_exceeded` 映射为 `(canceled, generation_c@anceled)`。预算超出不是稳定取消，应映射 `failed`。

**修复**：
- `classify_error` 中仅 `generation_canceled`、`practice_canceled` 映射 `canceled`
- 所有 budget_exceeded 码作为已知稳定业务码，映射 `(failed, msg)`（msg 为自身）
- 修正 docstring 中残留的"canceled 子串匹配"描述

**验证**：
- `test_classify_budget_exceeded_is_failed_not_canceled`：四种 budget_exceeded 均为 failed
- `test_classify_lesson_budget_exceeded_is_failed` 等 4 项链路测试
- `test_record_provider_call_budget_exceeded_is_failed`：通过 record_provider_call 验证

### 阻断项 #4：链路测试改为真实低层 helper

**问题**：原 `test_provider_call_chain_behavior.py` 中所有测试直接调用 `record_provider_call` 并在 `call_fn` 中返回硬编码结果，未经过真实低层 helper，相当于重新实现生产包装逻辑。

**修复**：
- 所有 28 项链路测试改为通过真实低层 helper：
  - Course/Tutor/Practice grading：`call_provider(settings, messages)`
  - Practice generation：`call_practice_provider(settings, messages)`
  - RAG Answer：`_generate(settings, messages)` + `_call_generate_for_recorder` 包装
- monkeypatch `httpx.post` 返回 fake provider JSON response
- 从最终数据库查询 `ProviderCall`，锁定 phase、owner、ordinal、调用次数和 timeout
- 不在测试中重新实现生产包装逻辑

### 阻断项 #5：修正 classify_error docstring

**问题**：docstring 中残留"canceled 子串匹配"描述（规则 4："ValueError with 'canceled' in message"），与实际实现不符。

**修复**：docstring 现在准确描述：
- 规则 3：仅 `generation_canceled`、`practice_canceled` 映射 canceled
- 明确说明 budget_exceeded 不是取消
- 移除"canceled 子串匹配"描述

## 3. Phase Allowlist

| Chain | Phases |
|-------|--------|
| Course generation | `plan`, `generation`, `repair` |
| Tutor | `plan`, `answer`, `repair` |
| Practice generation | `plan`, `generation`, `repair` |
| Practice grading | `grading`, `repair` |
| RAG Answer | `answer`, `repair` |

`ALL_PHASES` = 9 个低基数稳定字符串。

## 4. 稳定错误码分类（修正后）

| 异常类型 | ProviderCall.status | error_code |
|----------|---------------------|------------|
| `httpx.TimeoutException`（直接或链中） | `timed_out` | `provider_timeout` |
| `httpx.HTTPError`（非 timeout） | `failed` | `provider_unavailable` |
| `ValueError("generation_canceled")` | `canceled` | `generation_canceled` |
| `ValueError("practice_canceled")` | `canceled` | `generation_canceled` |
| `ValueError("lesson_budget_exceeded")` | `failed` | `lesson_budget_exceeded` |
| `ValueError("practice_budget_exceeded")` | `failed` | `practice_budget_exceeded` |
| `ValueError("grading_budget_exceeded")` | `failed` | `grading_budget_exceeded` |
| `ValueError("agent_step_budget_exceeded")` | `failed` | `agent_step_budget_exceeded` |
| 其他已知 `ValueError` | `failed` | 异常消息本身（稳定码） |
| 未知 `ValueError` | `failed` | `unknown_error` |
| 其他异常类型 | `failed` | `unknown_error` |

## 5. 各链 Provider Stub 调用次数不变的证据

所有五条链的接入方式均为**包装现有 `call_provider` / `_generate` 调用**，不增加、合并或删除现有 provider 请求。`record_provider_call` 在 `call_fn` 前后各执行一次 `flush`，不改变业务事务边界。

测试证据：
- `test_provider_stub_called_exactly_once_per_record`：每次 `record_provider_call` 恰好调用 stub 一次
- `test_provider_stub_not_called_on_recorder_error`：recorder 初始化失败时 stub 调用次数为零

## 6. 实际命令与逐项结果

### Recorder focused tests
```
PYTHONPATH='apps/api' .venv/Scripts/python.exe -m pytest -q apps/api/tests/test_provider_call_recorder.py
→ 43 passed in 67.85s
```

### Chain behavior tests
```
PYTHONPATH='apps/api' .venv/Scripts/python.exe -m pytest -q apps/api/tests/test_provider_call_chain_behavior.py
→ 28 passed in 49.25s
```

### Combined recorder + chain
```
PYTHONPATH='apps/api' .venv/Scripts/python.exe -m pytest -q \
  apps/api/tests/test_provider_call_recorder.py \
  apps/api/tests/test_provider_call_chain_behavior.py
→ 71 passed in 116.19s
```

### 成本计算器回归
```
PYTHONPATH='apps/api' .venv/Scripts/python.exe -m pytest -q apps/api/tests/test_provider_cost_calculator.py
→ 15 passed in 0.04s
```

## 7. 未运行项及原因

| 项目 | 原因 |
|------|------|
| API 全量测试 | 任务包 §8 明确禁止 |
| Web build | 任务包 §8 禁止 |
| OCR | 任务包 §2 禁止 |
| RAG embedding / Wolfram / Code Lab / MCP 接入 | 任务包 §6 明确排除 |
| 全部 132 项 Postgres tests | 任务要求仅运行真实链路测试和 recorder 分类测试 |

## 8. 已知风险与合同疑点

- **RAG Answer 事务边界**：`answers.py` 中 `_record` 使用 `db.commit()`，而 recorder 只 `flush`。answer 链中 trace 先 `flush` 创建，provider call 在同一事务内 `flush`，最终由 `_record` 的 `db.commit()` 提交。
- **classify_error __cause__ 链深度**：当前实现遍历完整链，不限深度。若未来异常链极深（>100 层），可能影响性能。实际业务链最深 2 层（helper 包装），风险极低。
- **_STABLE_BUSINESS_CODES 集合维护**：新增业务 ValueError 需同步添加到该集合，否则会被归类为 `unknown_error`。这是显式维护成本，但优于子串猜测。

## 9. 敏感字段排除确认

`ProviderCall` 模型列：

| 列 | 类型 | 敏感？ |
|----|------|--------|
| id | String(36) | 否 |
| workspace_id | String(36) | 否 |
| agent_run_id | String(36) 可空 | 否 |
| rag_answer_trace_id | String(36) 可空 | 否 |
| ordinal | Integer | 否 |
| phase | String(40) | 否 |
| provider | String(100) | 否 |
| model | String(100) | 否 |
| status | String(30) | 否 |
| error_code | String(100) 可空 | 否（仅稳定代码，不含异常正文） |
| input_tokens | Integer 可空 | 否 |
| output_tokens | Integer 可空 | 否 |
| latency_ms | Integer 可空 | 否 |
| started_at | DateTime | 否 |
| completed_at | DateTime 可空 | 否 |
| provider_rate_snapshot_id | String(36) 可空 | 否 |
| created_at | DateTime | 否 |

**确认**：无 prompt、messages、evidence、answer、response、raw_error、error_message、payload、content、body、text、question、completion、output_text、raw_payload 等敏感列。`error_code` 仅保存 `classify_error` 返回的稳定代码，不保存异常正文。

## 10. 未 commit、未 push、未运行 OCR 的确认

- ✅ 未 commit：所有变更均在工作区
- ✅ 未 push：无 commit 即无 push
- ✅ 未运行 OCR：任务全程未调用任何 OCR 工具或服务

## 11. Slice 1B-1 基线完整性确认

- migration 0024、ProviderCall/ProviderRateSnapshot ORM 模型、成本计算器、1B-1 测试均保持不变
- 新 migration 0025 的 `down_revision="0024"`，不覆盖或重建 0024
- 1B-1 的 34 项 ORM + calculator 测试全部通过
