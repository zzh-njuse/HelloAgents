# Stage 5 Part 1 Slice 1B-3：GLM 实现回交

状态：已通过独立验收
日期：2026-07-27

## 1. 修改文件与 Endpoint

### 新增文件

| 文件 | 用途 |
|---|---|
| `apps/api/learn_platform_api/schemas/provider_calls.py` | Pydantic 白名单 schema |
| `apps/api/learn_platform_api/services/provider_call_reads.py` | 只读 service（列表/详情/成本投影） |
| `apps/api/learn_platform_api/routers/provider_calls.py` | HTTP endpoint |
| `apps/api/tests/test_provider_call_read_api.py` | Focused HTTP tests（27 项） |

### 修改文件

| 文件 | 变更 |
|---|---|
| `apps/api/learn_platform_api/db/models.py` | 添加 `relationship` import 和 `ProviderCall.provider_rate_snapshot` 关系（`foreign_keys=[provider_rate_snapshot_id]`，因 Issue 2 复合 FK 导致歧义） |
| `apps/api/learn_platform_api/main.py` | 注册 `provider_calls.router` |
| `apps/api/learn_platform_api/routers/__init__.py` | 导出 `provider_calls` |

### Endpoint

```text
GET /api/v1/workspaces/{workspace_id}/provider-calls
GET /api/v1/workspaces/{workspace_id}/provider-calls/{provider_call_id}
```

## 2. 完整响应字段和过滤合同

### 响应字段（ProviderCallRead）

```text
id: str
owner.kind: "agent_run" | "rag_answer" | "workspace"
owner.agent_run_id: str | null
owner.rag_answer_trace_id: str | null
ordinal: int
phase: str
provider: str
model: str
status: str
input_tokens: int | null
output_tokens: int | null
latency_ms: int | null
error_code: str | null
started_at: datetime
completed_at: datetime | null
cost.currency: "CNY"
cost.status: "calculated" | "unknown"
cost.amount: str | null          # 固定八位小数字符串或 null
cost.unknown_reason: str | null   # provider_missing | model_missing | usage_missing | rate_missing
```

### 列表过滤参数

| 参数 | 类型 | 默认 | 范围 |
|---|---|---|---|
| `agent_run_id` | str \| null | null | — |
| `rag_answer_trace_id` | str \| null | null | — |
| `status` | started\|succeeded\|failed\|timed_out\|canceled \| null | null | — |
| `phase` | plan\|generation\|answer\|grading\|repair \| null | null | — |
| `limit` | int | 20 | 1..50 |

- `agent_run_id` 与 `rag_answer_trace_id` 不可同时提供（422）
- 列表稳定排序：`started_at DESC, id DESC`

## 3. Workspace 隔离与 404/422 行为

- 所有查询首先限定 `ProviderCall.workspace_id`
- Workspace 不活跃（lifecycle_status != "active"）→ 404
- 详情：不存在、已删除或属于其他 Workspace → 统一 404
- 列表：跨 Workspace owner filter → 空列表，不泄漏 owner 是否存在
- 两个 owner filter 同时出现 → 422
- 非法枚举（status/phase）→ 422
- limit 越界（0 或 >50）→ 422

## 4. Decimal/unknown 投影规则

- calculated amount：固定八位小数字符串（使用 `format(quantized, ".8f")` 避免 `0E-8` 科学计数法）
- 真实零成本：`"0.00000000"`（status=calculated，非 unknown）
- unknown amount：`null`
- unknown reason 严格优先级：provider_missing > model_missing > usage_missing > rate_missing
- 快照缺失或异常不可读 → `rate_missing`
- failed/timed_out/canceled 不改变计算规则，仍按实际 usage/快照计算
- 不回写任何数据库字段
- 不读取 settings 或"当前最新价格"

## 5. 查询数量证据

- 列表使用 `contains_eager` joined eager load 加载 `ProviderRateSnapshot`，避免 N+1
- 测试 `test_list_no_n_plus_one` 使用 SQLAlchemy `before_cursor_execute` 事件计数器
- 5 条 Provider Call 的列表查询总数 ≤ 4（含 workspace_is_active 检查）
- 无逐行快照查询

## 6. 禁止字段确认

测试 `test_response_excludes_forbidden_fields` 验证：

- 顶层字段精确匹配白名单：`{id, owner, ordinal, phase, provider, model, status, input_tokens, output_tokens, latency_ms, error_code, started_at, completed_at, cost}`
- owner 字段精确匹配：`{kind, agent_run_id, rag_answer_trace_id}`
- cost 字段精确匹配：`{currency, status, amount, unknown_reason}`
- 递归收集全部 JSON key，与 FORBIDDEN_KEYS 集合取交集，断言为空

禁止字段包括但不限于：prompt、message、question、answer、evidence、citation、response、payload、raw_error、http_body/header、key、api_key、base_url、url、hash、input_hash、file_path、provider_rate_snapshot_id、input_rate_per_1m、output_rate_per_1m、effective_at、created_at、question_hash、answer_hash、evidence_chunk_ids、citation_ids

## 7. 实际运行命令与逐项结果

### Provider Call Read API Tests

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -x apps/api/tests/test_provider_call_read_api.py -v
```

结果：**27 passed** (83.57s)

| # | 测试 | 结果 |
|---|---|---|
| 1 | test_list_and_detail_normal_response | PASSED |
| 2 | test_three_owner_kinds | PASSED |
| 3 | test_agent_run_filter | PASSED |
| 4 | test_status_filter | PASSED |
| 5 | test_phase_filter | PASSED |
| 6 | test_limit_filter | PASSED |
| 7 | test_rag_owner_filter | PASSED |
| 8 | test_double_owner_filter_returns_422 | PASSED |
| 9 | test_limit_boundary_and_invalid_enum_return_422 | PASSED |
| 10 | test_cross_workspace_owner_filter_empty_list | PASSED |
| 11 | test_cross_workspace_and_nonexistent_detail_same_404 | PASSED |
| 12 | test_stable_sort_started_at_desc_id_desc | PASSED |
| 13 | test_calculated_cost_fixed_eight_decimal | PASSED |
| 14 | test_real_zero_cost | PASSED |
| 15 | test_unknown_reason_provider_missing | PASSED |
| 16 | test_unknown_reason_model_missing | PASSED |
| 17 | test_unknown_reason_usage_missing | PASSED |
| 18 | test_unknown_reason_rate_missing | PASSED |
| 19 | test_future_price_does_not_change_historical_call | PASSED |
| 20 | test_failed_timed_out_canceled_compute_from_facts | PASSED |
| 21 | test_snapshot_unreadable_safe_degradation | PASSED |
| 22 | test_list_no_n_plus_one | PASSED |
| 23 | test_response_excludes_forbidden_fields | PASSED |
| 24 | test_inactive_workspace_returns_404 | PASSED |
| 25 | test_partial_usage_missing | PASSED |
| 26 | test_cost_uses_bound_snapshot_not_current | PASSED |
| 27 | test_unknown_priority_order | PASSED |

### AgentRun API Regression

```powershell
.\.venv\Scripts\python.exe -m pytest -x apps/api/tests/test_agent_run_api.py -v
```

结果：**24 passed** (75.64s)

### git diff --check

结果：仅有预先存在的 CRLF 警告（practice_generation.py, tutor_generation.py），无新增问题。

## 8. 未运行项及原因

| 项目 | 原因 |
|---|---|
| API 全量测试 | 任务包明确不要求，仅 focused + regression |
| Web build | 任务包明确不要求 |
| 真实 provider 调用 | 任务包禁止 |
| OCR | 任务包禁止 |
| Docker Compose | 任务包不要求 |
| Postgres migration 测试 | 不新增 migration |
| 1B-1/1B-2 Postgres 专项测试 | 保留不变，不重新运行 |

## 9. 已知风险或合同疑点

1. **ORM relationship 歧义**：ProviderCall → ProviderRateSnapshot 存在两条 FK 路径（简单 FK + Issue 2 复合 FK），必须在 relationship 声明中指定 `foreign_keys=[provider_rate_snapshot_id]`。此为 SQLAlchemy 对复合 FK 的标准处理，不影响数据库约束或写入行为。

2. **Decimal 零值格式化**：Python `str(Decimal("0").quantize(...))` 产生 `"0E-8"` 而非 `"0.00000000"`。已使用 `format(quantized, ".8f")` 确保固定小数点表示。此为 Python Decimal 的已知行为，不影响计算精度。

3. **快照异常不可读的测试局限**：由于 DB CHECK 约束阻止创建包含异常数据的 ProviderRateSnapshot 行，测试通过 NULL snapshot_id 路径覆盖 rate_missing 场景。若未来需要测试"snapshot 行存在但数据异常"，需在测试中临时关闭约束或使用 mock，当前任务包不要求此路径。

4. **SQLite 测试 vs Postgres**：测试使用 SQLite（conftest 现有模式），复合 FK 在 SQLite 中不强制。Workspace 隔离和 provider/model 一致性由 Postgres 专项测试覆盖（1B-1/1B-2 baseline）。

## 10. 确认

- ✅ 未 commit
- ✅ 未 push
- ✅ 未运行 OCR
- ✅ 不进入 Slice 1C
- ✅ 不执行统一 OCR
- ✅ 不新增 migration
- ✅ 不修改 AgentRunDetail
- ✅ 不新增 Web、聚合、价格管理或业务写入
- ✅ 不修改 Provider Call 写入、业务 orchestration、价格选择
- ✅ 不调用真实 provider
- ✅ 不安装依赖
- ✅ 不读取或修改 .tmp/、artifacts/
- ✅ Slice 1B-1/1B-2 baseline 保持不变
