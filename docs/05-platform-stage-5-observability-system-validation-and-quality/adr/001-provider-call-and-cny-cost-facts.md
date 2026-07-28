# ADR 001：独立 Provider Call 与人民币价格快照

状态：已接受（2026-07-27）

日期：2026-07-27

## 背景

现有 AgentRun 只保存聚合 token，AgentToolCall 表示工具阶段。两者都不能证明一次
真实 provider 请求使用了哪个 provider/model、发生了几次 repair/retry，或采用
哪一版价格。使用当前设置反推历史金额会制造错误成本事实。

## 决策

1. 新建独立 Provider Call 事实，不复用 AgentToolCall，也不把多个调用覆盖进
   AgentRun 聚合字段。
2. Provider/model、usage、状态和价格均以调用时快照保存。
3. 币种固定 CNY，单价按每百万 input/output token 分开保存。
4. Decimal 是数据库和领域计算的唯一金额类型；未来 JSON 使用字符串。
5. 只有 provider、model、双维 usage 和双维价格完整时计算金额。
6. 缺失时金额为 unknown，并记录稳定原因；不得估算、补零或读取当前价格。
7. 失败、超时、取消也保留事实；Workspace/AgentRun 删除继续是删除权威。
8. Slice 1B-1 不接入业务链、不提供 API/Web、不 backfill 历史数据。

## 结果

优点：

- repair/retry 和多个 provider 请求不会互相覆盖；
- 历史成本不随配置变化；
- unknown 与真实零成本可区分；
- 后续读取层不需要接触敏感正文；
- 跨 Workspace 错绑调用在 DB 层被拒绝（Issue 1，复合外键，人工批准 2026-07-27）；
- 错绑价格在 DB 层被拒绝（Issue 2，复合外键）。

代价：

- 新增 migration 和写入事实；
- 业务接入必须在 1B-2 逐链验证；
- 没有完整 usage/价格的调用无法计算金额；
- Issue 1 需对既有 `agent_runs` 表加冗余 `UNIQUE(id, workspace_id)`（零行为变化，`id` 已是 PK）。

## DB 层完整性加固（2026-07-27 人工批准）

独立验收提出两个阻断问题，均以复合外键在 DB 事实层修复：

1. **Issue 1（Workspace 隔离）**：`provider_calls(agent_run_id, workspace_id) → agent_runs(id, workspace_id)`。MATCH SIMPLE 下 `agent_run_id IS NULL` 时外键跳过；非空时强制 workspace 一致。`ON DELETE CASCADE` 是必要的（SQLAlchemy DDL 顺序使复合外键先于简单外键，Postgres 按此顺序检查）。引用目标 `agent_runs(id, workspace_id)` 需唯一约束；`id` 已是 PK，故该 UNIQUE 永不可能违反。这是对既有 `agent_runs` 的最小加性改动，已获人工批准随 migration 0024 并入。

2. **Issue 2（错绑价格）**：`provider_calls(provider_rate_snapshot_id, provider, model) → provider_rate_snapshots(id, provider, model)`。MATCH SIMPLE 下 `provider_rate_snapshot_id IS NULL` 时外键跳过；绑定时强制 provider/model 一致。

## 排除方案

- 扩展 AgentToolCall：语义错误，Tool 不等于 provider 请求；
- 只扩展 AgentRun：无法表达一次 attempt 内多个调用；
- 读取当前价格计算历史金额：会改写历史含义；
- 多币种和实时汇率：超出 self-host 最小成本观测范围。

## OCR 策略

1B-1、1B-2、1B-3 分别完成 focused tests 和轻量合同验收，三部分结束后统一制作
仓库外白名单副本并分块 OCR。已知 High 风险不得以“等待最终 OCR”为由暂缓。
