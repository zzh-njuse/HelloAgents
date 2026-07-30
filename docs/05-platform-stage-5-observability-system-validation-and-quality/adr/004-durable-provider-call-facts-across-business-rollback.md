# ADR 004：业务回滚后的 Provider Call 事实持久化

状态：已于 2026-07-28 通过人工 Gate

日期：2026-07-28

## 1. 决策摘要

Provider Call 是已经发生的外部副作用事实，不能因为业务 artifact、Turn 或 Job
事务回滚而消失。

建议采用“先持久化 owner，再以独立短事务记录调用事实”的边界：

1. outbound request 前，业务 orchestration 必须先让 AgentRun 或
   RagAnswerTrace 成为已提交、可引用的 owner；
2. Provider Call 的 `started`、成功和受控失败最终化使用独立短事务；
3. Provider Call 写入失败时不得发送 provider 请求；
4. 业务 artifact 仍在原业务事务中提交或回滚，不与观测事实互相冒充原子；
5. worker 最终状态继续由既有权威路径写入，Provider Call 不反向决定重试。

该决策取代 ADR 002 中“recorder 与业务事务同生共死”的限制，但不改变 provider
调用次数、prompt、artifact、重试预算、价格选择或公开读取合同。

## 2. 触发证据

Slice 2A 的真实 Tutor 纵向测试经过：

```text
HTTP API -> Redis -> 独立 RQ worker -> Postgres -> Qdrant -> HTTP provider stub
```

验证结果：

- 正常路径产生 `plan/answer` Provider Call；
- repair 路径产生 `plan/answer/repair` Provider Call；
- timeout 后 TutorTurn 正确进入 `retry_wait`；
- timeout 后 AgentRun 正确记录稳定业务错误；
- recorder 在异常抛出前已形成 `timed_out/provider_timeout`；
- worker 随后执行业务事务 rollback，最终数据库中该 Provider Call 为 0 条。

因此现状违反 Spec 003“正常返回和受控异常必须持久化最终状态”，也违反
Spec 006 对真实 timeout 事实的验收要求。这不是测试假设问题。

## 3. 不变量

### 3.1 外部副作用事实

每次实际发送的 provider request attempt 必须留下且只留下一条 Provider Call。
业务 artifact 后续失败、校验失败或事务回滚，不能删除已发生的请求事实。

### 3.2 发送前约束

`started` 必须在网络请求前提交。Workspace、owner、provider/model 价格绑定或
ordinal 约束失败时，网络请求不得发生。

### 3.3 最终化

- 正常返回：`succeeded`；
- timeout：`timed_out/provider_timeout`；
- 已知失败和取消：使用既有稳定状态与错误码；
- provider 返回成功但 artifact 校验失败：该次调用仍为 `succeeded`；
- 进程在请求后、最终化前被强杀：允许保留 `started`，后续由诊断或恢复流程识别，
  不得伪造结果。

### 3.4 安全

独立事务仍只写既有白名单字段，不写 prompt、question、answer、response、
异常正文、API key、内部 URL 或绝对路径。

## 4. 实现边界

建议由共享 recorder 统一拥有独立 Session 生命周期，五条链不得各自复制事务
处理。业务 orchestration 只传递稳定 owner、phase、provider/model 和调用函数。

实施时必须证明：

- owner 在 `started` 提交前已经持久化；
- 同一 owner 的 ordinal 仍单调且唯一；
- recorder start 提交失败不会调用 provider；
- recorder finalize 失败不会被报告成完整成功事实；
- timeout 业务回滚后 Provider Call 仍可查询；
- 删除 owner 或 Workspace 时既有级联仍有效；
- 不新增 provider 调用或自动重试。

如果现有 owner 创建与业务 artifact 写入耦合，允许把 owner 建立拆成一个明确的
前置事务，但不得提前提交回答、课节、练习、评分等半成品业务数据。

## 5. 影响

### 正面

- 成本、timeout 和失败率不再因业务 rollback 被系统性低估；
- `started` 能表达调用已发出但最终状态未知；
- 五条链共享同一事实语义；
- Slice 2A 可以用真实系统路径锁定行为。

### 代价

- Provider Call 与业务 artifact 不再是同一数据库事务；
- owner 必须先于请求成为持久事实；
- 需要处理 finalize 写入失败和进程强杀后的 `started`；
- 事务数量增加，但每次仅为小型观测事实写入；
- 必须回归删除级联、workspace 约束和 ordinal 并发。

## 6. 未采用方案

- **让系统测试接受 0 条失败调用**：会隐藏真实成本和失败事实，违反已接受 Spec。
- **仅在 Tutor worker rollback 后补写一条**：五条链语义分叉，且不能证明请求前
  `started` 约束。
- **在异常处理中直接 commit 当前业务 Session**：可能一并提交无效或半成品
  artifact。
- **只使用 savepoint**：外层 rollback 仍会删除 savepoint 内事实。
- **把异常正文写入补偿队列**：扩大敏感信息面，且不能解决请求前约束。
- **本阶段引入独立观测数据库**：部署和一致性复杂度过高；同一 Postgres 的独立
  Session 已足够形成独立事务。

## 7. 验收

最低要求：

1. Tutor 真实 timeout 纵向测试最终查询到一条
   `plan/timed_out/provider_timeout`；
2. Tutor 正常和 repair 纵向测试继续通过；
3. 五条业务 orchestration 的正常、repair/失败 Provider Call 合同通过；
4. recorder 写入失败的反例证明 provider 未被调用；
5. Postgres workspace、owner、ordinal、价格绑定和删除级联回归通过；
6. API focused regression、Web lint/build 和 `git diff --check` 通过；
7. 不调用真实 provider，不运行付费 OCR。

## 8. 人工 Gate

开始产品实现前需确认：

1. 接受 Provider Call 作为独立持久化的外部副作用事实；
2. 接受为此先提交最小 owner，再发送 provider 请求；
3. 接受进程强杀时可能保留 `started`，本 Slice 不自动猜测最终结果；
4. 接受该合同统一适用于五条链，而不是只修 Tutor。
