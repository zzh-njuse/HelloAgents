# Spec 002：Provider Call 与人民币成本事实基础

状态：已接受（2026-07-27）

日期：2026-07-27

适用范围：Platform Stage 5 第一部分 Slice 1B-1

## 1. 目标

建立 Provider Call、人民币价格快照和纯成本计算的最小权威合同，为后续调用链接入
和安全读取提供稳定基础。

本 Slice 只实现 schema、migration、领域计算和 focused tests，不接入 Course、
Tutor、Practice、RAG Answer，不新增 API/Web，也不调用真实 provider。

## 2. 核心合同

### Provider Call

每条记录代表一次真实生成 provider 请求尝试，不是 Agent step 或 Tool call。

最小事实：

- Workspace；
- 可选 AgentRun owner；
- 稳定 ordinal 与 phase；
- provider/model 快照；
- `started|succeeded|failed|timed_out|canceled` 状态；
- input/output token，可分别缺失；
- latency、稳定错误码、开始/完成时间；
- 可选人民币价格快照；
- 计算成本或稳定 unknown reason。

不得保存 prompt、message、evidence、回答、provider 原始响应或原始错误。

### 人民币价格

- 币种固定为 CNY；
- 人工维护 provider/model 的 input/output 单价；
- 单价按每 1,000,000 token 表示；
- Provider Call 绑定不可变价格快照，历史调用不读取当前配置反推；
- 金额使用 Decimal，API 层未来返回十进制字符串，不使用 float。

### 成本计算

只有下列事实同时完整时才产生计算成本：

- provider；
- model；
- input tokens；
- output tokens；
- input CNY rate；
- output CNY rate。

公式：

```text
input_cost = input_tokens * input_rate_per_1m / 1,000,000
output_cost = output_tokens * output_rate_per_1m / 1,000,000
calculated_cost = input_cost + output_cost
```

任一事实缺失时金额为 unknown，不以 `0`、当前设置或文本长度补值。

稳定 unknown reason：

```text
provider_missing
model_missing
usage_missing
rate_missing
```

同一记录只返回一个原因，优先级按上列顺序。

## 3. 生命周期

- Provider Call 随 Workspace 删除；
- 绑定 AgentRun 时随 AgentRun 删除；
- 不在本 Slice 建立独立保留期或跨 Workspace 引用；
- 失败、超时和取消仍可保留调用事实，因为请求可能已经产生费用；
- 历史 AgentRun 不做猜测性 backfill。

### 3.1 Workspace 隔离（Issue 1，人工批准 2026-07-27）

当 Provider Call 绑定 AgentRun 时，两者的 `workspace_id` 必须一致；跨 Workspace 绑定在 DB 层被拒绝。

实现：`provider_calls(agent_run_id, workspace_id) → agent_runs(id, workspace_id)` 复合外键（`fk_provider_calls_run_workspace`，`ON DELETE CASCADE`）。MATCH SIMPLE 语义下 `agent_run_id IS NULL` 时外键跳过（workspace-only 调用不受限）。

引用目标 `agent_runs(id, workspace_id)` 需唯一约束；`id` 已是主键，故 `UNIQUE(id, workspace_id)` 永不可能违反，纯为满足复合外键目标而存在。这是对既有 `agent_runs` 表的最小、冗余、纯加性改动，已获人工批准随 migration 0024 并入。

`ON DELETE CASCADE` 在复合外键上是必要的：SQLAlchemy 按声明顺序发射 DDL，复合外键先于简单外键；Postgres 按此顺序检查约束，`NO ACTION` 会在简单 FK 的 CASCADE 生效前阻断删除。

### 3.2 绑定快照时 provider/model 一致（Issue 2）

当 Provider Call 绑定价格快照时，调用的 `provider`/`model` 必须与快照一致；错绑价格在 DB 层被拒绝。

实现：`provider_calls(provider_rate_snapshot_id, provider, model) → provider_rate_snapshots(id, provider, model)` 复合外键（`fk_provider_calls_snapshot_provider_model`）。MATCH SIMPLE 语义下 `provider_rate_snapshot_id IS NULL` 时外键跳过。

## 4. 文件与实现边界

候选修改仅限：

- ORM model；
- 一份 Alembic migration；
- Provider Call/cost 领域 service；
- focused ORM、migration 和成本计算测试；
- 必要的 Stage 5 文档。

禁止修改 worker、provider adapter、Course/Tutor/Practice/RAG 执行链、Run/Tool API、
Web、prompt、依赖或 Compose。

## 5. 验证 Gate

- migration upgrade/downgrade 或仓库既有 migration 合同通过；
- Decimal 对完整、partial 和大 token 输入保持确定性；
- 价格更新不改写已绑定的历史快照；
- ordinal 能区分同一 Run 内多个调用；
- 缺失事实始终返回稳定 unknown reason；
- Workspace/AgentRun 删除不留下孤立 Provider Call；
- schema 不含任何敏感正文或原始 provider payload；
- 不发生真实付费调用；
- 跨 Workspace 绑定被 DB 层拒绝（Issue 1，复合外键实证）；
- 绑定快照时 provider/model 必须一致（Issue 2，复合外键实证）。

## 6. 后续边界

- Slice 1B-2 才接入 Course、Tutor、Practice 和 RAG Answer；
- Slice 1B-3 才提供安全读取 API；
- 1B-1/1B-2/1B-3 全部完成后统一执行白名单分块 OCR；
- 任一部分发现错账、跨 Workspace、删除失败或敏感信息风险时提前停止，不等待最终
  OCR。

## 7. 人工 Gate

2026-07-27 已接受上述范围、事实模型、CNY 价格快照、严格 unknown
语义、不 backfill 历史数据，以及 1B 三部分结束后统一执行 OCR。
