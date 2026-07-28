# Stage 5 Part 1 Slice 1B-3：GLM 实现任务包

状态：可执行
日期：2026-07-27

## 1. 目标

实现安全、只读的 Provider Call 列表与详情 API，投影每次调用的 owner、phase、
状态、usage、延迟、稳定错误和 CNY 成本。

权威合同：

- [Spec 004](specs/004-safe-provider-call-read-api.md)
- [Spec 003](specs/003-provider-call-business-instrumentation.md)
- [ADR 002](adr/002-provider-call-recording-lifecycle-and-rag-owner.md)
- [Spec 002](specs/002-provider-call-cost-foundation.md)
- [ADR 001](adr/001-provider-call-and-cny-cost-facts.md)

本任务一次完成，不拆分。遇到合同冲突或需要新增 migration、Web、聚合时停止，
不得自行扩大。

## 2. 运行环境与基线

- Windows PowerShell
- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- Python：仓库现有 `.venv`
- API：`apps/api`
- 当前分支：`main`
- Slice 1B-1/1B-2 的 migration `0024`/`0025`、模型、recorder 和测试仍是
  未提交的合法工作区基线，不得回滚、覆盖或重新实现
- 不新增 migration，不安装依赖，不修改 Compose
- 不读取或改动 `.tmp/`、`artifacts/`
- 不调用真实 provider，不运行 OCR，不 commit，不 push

开始前完整读取根 `AGENTS.md`、Playbook、GLM handoff workflow、本任务包及五份
权威合同，并检查 `git status --short --branch`。

## 3. 允许修改

按仓库现有分层最小修改：

- 新 Provider Call router；
- 新 Provider Call Pydantic schema；
- 新 Provider Call 只读 service；
- router 注册文件；
- focused HTTP/ORM tests；
- Stage 5 handback。

允许复用 `provider_cost.calculate_cost`，但不得修改 Provider Call 写入、业务
orchestration、价格选择、AgentRunDetail、RAG/Course/Tutor/Practice 响应或 Web。

如发现 1B-1/1B-2 的确定性 bug，停止并在 handback 说明，不借读取 API 顺手重构。

## 4. API 合同

实现：

```text
GET /api/v1/workspaces/{workspace_id}/provider-calls
GET /api/v1/workspaces/{workspace_id}/provider-calls/{provider_call_id}
```

列表 query：

- `agent_run_id: str | null`
- `rag_answer_trace_id: str | null`
- `status: started|succeeded|failed|timed_out|canceled | null`
- `phase: plan|generation|answer|grading|repair | null`
- `limit: int = 20`，范围 `1..50`

两个 owner filter 同时出现返回 422。不要把动态数据库值用来扩展 phase/status
枚举。列表稳定排序为 `started_at DESC, id DESC`。

Workspace 不活跃返回 404。详情使用 Workspace + call ID 读取；不存在、已删除或
属于其他 Workspace 均返回相同 404。跨 Workspace owner filter 返回空列表，
不得泄漏 owner 是否存在。

## 5. 响应白名单

建立显式 Pydantic schema，不使用 ORM 自动展开：

```text
ProviderCallOwnerRead
  kind: agent_run | rag_answer | workspace
  agent_run_id: string | null
  rag_answer_trace_id: string | null

ProviderCallCostRead
  currency: CNY
  status: calculated | unknown
  amount: string | null
  unknown_reason:
    provider_missing | model_missing | usage_missing | rate_missing | null

ProviderCallRead
  id
  owner
  ordinal
  phase
  provider
  model
  status
  input_tokens
  output_tokens
  latency_ms
  error_code
  started_at
  completed_at
  cost
```

禁止加入 rate snapshot ID、费率、created_at 之外的内部 ORM 字段，尤其不得返回
prompt、message、question、answer、evidence、citation、response、payload、
raw error、HTTP body/header、key、URL、hash 或路径。

## 6. 成本投影

只使用 Provider Call 已绑定并随查询加载的 `ProviderRateSnapshot`：

- 调用 `calculate_cost`，不得复制公式；
- 不读取 settings 或“当前最新价格”；
- calculated amount 使用固定八位小数字符串；
- 真实零成本为 `"0.00000000"`；
- unknown amount 为 `null`；
- unknown reason 严格复用 1B-1 优先级；
- 快照缺失或异常不可读时按 `rate_missing`；
- 不因 call status 是 failed/timed_out/canceled 而改变计算规则；
- 不回写任何数据库字段。

不得使用 float、JSON number 或科学计数法表达金额。

## 7. 查询与性能

- 每条 SQL 首先限定 `ProviderCall.workspace_id`；
- owner/status/phase filter 在该限定上继续收窄；
- 详情同样首先限定 Workspace；
- 列表一次加载计算所需价格快照，避免逐行查询；
- 不新增持久化聚合、缓存、物化视图或 count query；
- 不修改现有 AgentRun API。

使用现有仓库模式实现依赖注入、Workspace active 检查和 HTTP 错误文案。

## 8. 最低测试

必须通过公开 HTTP API 和真实 ORM 构造数据，覆盖：

- Workspace 列表和详情正常响应；
- AgentRun、RAG、Workspace-only 三种 owner；
- agent_run/status/phase/limit filter；
- RAG owner filter；
- 两个 owner filter 同时存在返回 422；
- limit 边界和非法枚举返回 422；
- 跨 Workspace owner filter 空列表；
- 跨 Workspace/不存在详情相同 404；
- `started_at DESC, id DESC` 稳定排序；
- calculated cost 固定八位；
- 真实零成本；
- provider/model/usage/rate 四种 unknown reason；
- 未来/后续价格不改变已绑定历史调用；
- failed/timed_out/canceled 只按事实计算；
- snapshot FK 异常不可读取时安全降级；
- 列表无 N+1，可用 SQLAlchemy query counter 锁定查询数量；
- 响应 JSON 不含禁止字段；
- `test_agent_run_api.py` 回归。

不得用源码字符串检查替代 HTTP 行为。不要为了制造无法由数据库产生的状态而
关闭外键或破坏事实约束；异常快照场景应采用安全且可解释的测试方式。

## 9. 建议验证

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q <新增 Provider Call API tests>
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py
git diff --check
```

不运行 API 全量、Web build、真实 provider 或 OCR，除非 focused regression
暴露直接相关问题。

## 10. 交回

生成 `PART_1_SLICE_1B3_GLM_HANDBACK.md`，包含：

- 修改文件与 endpoint；
- 完整响应字段和过滤合同；
- Workspace 隔离与 404/422 行为；
- Decimal/unknown 投影规则；
- 查询数量证据；
- 禁止字段确认；
- 实际运行命令与逐项结果；
- 未运行项及原因；
- 已知风险或合同疑点；
- 未 commit、未 push、未运行 OCR 的确认。

完成后停止，不进入 Slice 1C，也不执行统一 OCR。
