# Stage 5 Part 1 Slice 1B-1：GLM 实现任务包

状态：可执行
日期：2026-07-27

## 1. 目标

实现 Provider Call、CNY 价格快照和纯 Decimal 成本计算的最小事实基础。
本切片不接入任何真实业务调用链，不新增 API/Web，不调用真实 provider。

权威合同：

- [Spec 002](specs/002-provider-call-cost-foundation.md)
- [ADR 001](adr/001-provider-call-and-cny-cost-facts.md)

遇到合同不明确或需要扩大范围时停止并写入 handback，不自行扩展。

## 2. 运行环境

- Windows PowerShell
- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- Python：优先使用仓库现有 `.venv`
- API：`apps/api`
- Alembic 当前 head：`0023`；本切片只允许新增 `0024`
- Postgres migration 验证只可使用隔离、可丢弃数据库
- 不安装依赖，不修改 Compose，不读取或改动 `.tmp/`、`artifacts/`
- 不 commit，不 push

开始前读取根 `AGENTS.md`、`docs/README.md`、Playbook、GLM handoff workflow、
本任务包及两份权威合同，并检查 `git status --short --branch`。

## 3. 允许修改

- `apps/api/learn_platform_api/db/models.py`
- `apps/api/alembic/versions/0024_add_provider_call_cost_foundation.py`
- 新增一个聚焦的成本领域 service
- 新增 focused ORM、成本计算和 Postgres migration tests
- `PART_1_SLICE_1B1_GLM_HANDBACK.md`

如现有结构要求不同文件名，可在同一边界内调整并在 handback 说明。

## 4. 必须实现

### 4.1 Provider rate snapshot

新增独立、只增不改的价格快照事实，至少包含：

- `provider`、`model`
- 固定 `currency=CNY`
- Decimal `input_rate_per_1m`、`output_rate_per_1m`
- 生效时间与创建时间
- 防止相同 provider/model/effective time 重复的约束
- 非负费率约束

不得提供更新或删除价格快照的业务方法。

### 4.2 Provider call

新增独立 Provider Call 事实，至少包含：

- Workspace owner；可选 AgentRun owner
- 稳定 `ordinal`、`phase`
- provider/model 快照
- `started|succeeded|failed|timed_out|canceled`
- 可空的 input/output tokens、latency、稳定 error code
- 开始/完成时间
- 可选价格快照引用

约束必须覆盖非负 token/latency、合法状态和 owner 生命周期。绑定 AgentRun
时随 AgentRun 删除；所有记录随 Workspace 删除。不得保存 prompt、message、
evidence、回答、provider 原始响应或原始错误。

### 4.3 Pure cost calculator

实现无数据库写入副作用的纯 Decimal 计算：

```text
tokens * rate_per_1m / 1,000,000
```

- 双组 usage 与双组 rate 完整时才返回 CNY Decimal；
- `0` token 是有效事实，不是 missing；
- 不使用 float，不从当前配置反推；
- unknown 原因和优先级严格为：
  `provider_missing`、`model_missing`、`usage_missing`、`rate_missing`；
- 空白 provider/model 视为 missing；
- 结果必须稳定区分真实零成本和 unknown；
- 不把派生总成本重复持久化到 Provider Call。

Decimal 精度与舍入规则须集中定义并由测试锁定，不得散落在调用方。

## 5. 明确禁止

- 修改 worker、provider adapter、Course/Tutor/Practice/RAG 执行链
- 新增路由、公开 schema、Web 或 dashboard
- 修改 AgentRun/AgentToolCall 的既有公开合同
- 历史 backfill、真实 provider 请求、embedding/Wolfram/Code Lab 定价
- 新依赖、无关重构、格式化扩散
- 针对固定测试输入的捷径

## 6. 最低测试

必须覆盖：

- ORM 关系、级联删除和数据库约束；
- migration `0023 -> 0024 -> 0023`，且只在隔离 Postgres 执行；
- 完整、零 token、部分 usage、大 token 的 Decimal 计算；
- 四个 unknown 原因及其优先级；
- 新价格快照不改变旧 Provider Call 的历史含义；
- 禁止字段不进入模型或公开输出；
- 相关 AgentRun 回归测试保持通过。

建议验证：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q <新增 focused tests> apps/api/tests/test_agent_run_api.py
git diff --check
```

若没有隔离 Postgres，migration 集成测试必须明确 skip 并在 handback 写清楚，
不得用 SQLite 冒充通过。不要运行 OCR；三个 1B 小切片结束后统一执行。

## 7. 交回要求

生成 `PART_1_SLICE_1B1_GLM_HANDBACK.md`，包含：

- 修改文件与行为摘要
- schema/约束/Decimal 规则
- 实际运行的命令和逐项结果
- 未运行检查及原因
- 已知风险、合同疑点和是否建议进入独立验收
- 确认未 commit、未 push

完成后停止，不自行进入 1B-2。
