# ADR 006：远程工具事实独立持久化与授权额度原子消费

状态：已于 2026-07-30 通过人工 Gate

日期：2026-07-30

## 1. 决策

采用一个共享的 Remote Tool Call recorder。它复用 ADR 004 的独立短事务模式，
但同时承担“发送资格预留”：

1. `reserve()` 在同一个独立事务中条件递增授权 `used_calls`，并插入
   `AgentToolCall(status=started)`；
2. 只有 `reserve()` 提交成功后，调用方才能执行 Judge0 / Wolfram 请求；
3. `succeed()`、`fail()`、`timeout()` 分别在独立短事务中最终化；
4. 业务 Session 不持有、递增或回写受管授权计数；
5. recorder 只接收稳定 ID、ordinal 和白名单标量，不接收跨 Session ORM 实例。

## 2. 为什么必须把额度与 started 放在同一事务

如果先扣额度、后写 Tool Call，进程可能只留下额度而没有调用事实；如果先写
Tool Call、后扣额度，则可能留下没有取得发送资格的假调用。将两者放在一个
Postgres 事务中，可以形成一个明确边界：

```text
没有提交 reserve -> 不得发送
reserve 已提交     -> 额度已消费，且 started 事实存在
```

外部远程请求本身不能与 Postgres 组成分布式原子事务。因此进程在发送前后崩溃时，
最多保留一个 `started`，而不是伪造最终状态或恢复额度。

## 3. 并发策略

授权消费使用单条条件更新：

```sql
UPDATE ... SET used_calls = used_calls + 1
WHERE id = :id
  AND workspace_id = :workspace_id
  AND used_calls < max_calls
RETURNING used_calls, max_calls;
```

返回零行表示授权不存在、Workspace 不匹配或预算耗尽。调用方只得到稳定分类，
不得根据异常正文区分内部结构。

`AgentToolCall` 使用调用方编排产生的 ordinal，并由既有数据库唯一约束
`uq_agent_tool_calls_ordinal(agent_run_id, ordinal)` 防止重试或并发重复记录；
本次只补齐 ORM 声明，不重复创建约束。

## 4. Session 与 owner

- AgentRun 必须在 `reserve()` 前已经提交；
- Tutor Turn、Practice Job 及其授权在现有 API 创建事务中已持久化；
- Course generation 若在 worker 内首次创建工具授权，只允许在真正需要首次远程
  调用前提交最小授权快照，不得顺带提交 LessonVersion、citation 或其他半成品；
- 独立 recorder Session 不提交、回滚、关闭或刷新调用方业务 Session；
- 调用方不得在独立消费后把旧的 `used_calls` 写回数据库。

## 5. 数据库变更

新增 migration：

- 将 Agent Tool Call 的 run/workspace 绑定提升为复合外键；
- 补齐 ORM 中遗漏的既有 `(agent_run_id, ordinal)` 唯一约束声明；
- 保证删除 AgentRun 时 Tool Call 级联删除；
- 为 Job/Tutor 两类授权增加合法额度 CHECK。

migration 在增加约束前检查既有重复 ordinal、跨 Workspace 绑定和非法额度；发现
坏数据时明确失败，不自动改写历史事实。

## 6. 错误处理

只允许稳定、低基数错误码，例如：

- `tool_budget_exceeded`
- `tool_authorization_invalid`
- `tool_timeout`
- `backend_unavailable`
- `schema_drift`
- `tool_call_error`
- `unknown_tool_error`

不得持久化 `str(exc)`、远程响应正文或连接地址。

finalize 找不到对应 started 记录时抛出稳定的 recorder 错误。若业务异常与
finalize 异常同时发生，保留原始业务异常作为主异常，并保留 recorder 异常因果链。

## 7. 未采用方案

- **继续依赖业务事务**：失败回滚会删除已经发生的外部调用事实；
- **失败后补写一条 Tool Call**：无法证明发送前取得授权，也会丢失进程崩溃场景；
- **只独立写 Tool Call、仍在业务事务扣额度**：事实与额度会分叉；
- **失败时返还额度**：远程成本已经发生，会允许重试突破原预算；
- **对授权行使用长事务行锁并覆盖远程调用**：会长时间占锁并放大并发阻塞；
- **引入消息队列/outbox 作为本次修正**：复杂度超过当前单体 Postgres 的需要。

## 8. 影响

正面影响：

- 失败漏斗、工具使用率和额度事实可信；
- 并发不会突破预算；
- 后续 C++ / Wolfram 优化有可靠证据。

代价：

- 每个远程 attempt 增加一次 reserve 和一次 finalize 短事务；
- 外部调用后崩溃可能留下 `started`；
- 五条调用路径必须统一迁移，不能保留部分旧式 `used_calls += 1`。

## 9. 人工确认点

接受本 ADR 即表示接受 Spec 008 第 8 节的五项边界，并授权新增 migration 与五条
远程工具路径的统一改造。真实远程 pilot 仍在受控回归全部通过后单独执行，避免
用付费调用调试事务实现。

以上决策已于 2026-07-30 获人工接受。
