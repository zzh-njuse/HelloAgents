# Spec 008：失败回滚后仍可信的远程工具调用事实与额度

状态：已于 2026-07-30 通过人工 Gate

日期：2026-07-30

## 1. 背景

Slice 2B 真实远程 Gate 已证明：Practice 或 Tutor 在调用 Judge0 / Wolfram 后，
如果后续 artifact 校验或业务事务失败，当前事务中的 `AgentToolCall` 和
`used_calls` 会一起回滚。结果是：

- 外部调用真实发生，但运行记录显示没有调用；
- 已消耗的工具额度可能恢复，重试后再次调用；
- 不能区分“没有请求工具”和“工具已调用但后续业务失败”；
- Wolfram 使用率、失败漏斗和远程成本判断不可信。

这属于 Slice 2B 验收事实缺失，不属于第三部分的生成质量优化。

## 2. 目标

对于受 `JobToolAuthorization` 或 `TutorTurnToolAuthorization` 管理的远程
Judge0 / Wolfram 调用：

1. 每个准备发送的远程 attempt 在发送前原子消费一次额度；
2. 同一事务写入一条 `started` Agent Tool Call；
3. 成功、受控失败和 timeout 使用独立短事务最终化；
4. 后续业务 artifact 回滚不得删除调用事实或恢复额度；
5. 并发请求不能突破 `max_calls`；
6. 报告只读取脱敏事实，不从异常文本或远程正文猜测调用结果。

## 3. 范围

必须接入：

- Course generation 的 Wolfram 科学验证；
- Practice generation 的代码 reference validation；
- Practice generation 的 Wolfram 科学验证；
- Tutor 的代码执行；
- Tutor 的 Wolfram 科学计算。

普通检索、Skill 加载、上下文选择等没有远程计费或授权额度的内部
`AgentToolCall` 保持现有业务事务语义，不在本修正中改造。

Code Lab 自身已有独立的 `CodeLabRun` / `CodeLabJob` 权威状态，本修正不改变
其执行合同；只处理上述由 Job/Turn 工具授权驱动的嵌入式远程调用。

## 4. 行为合同

### 4.1 发送前预留

共享 recorder 在独立 Postgres 短事务中完成：

- 验证 AgentRun、Workspace、授权和业务 owner 一致；
- 使用条件更新执行 `used_calls = used_calls + 1`，条件为
  `used_calls < max_calls`；
- 插入 `status=started` 的 Agent Tool Call；
- 提交成功后才允许调用远程工具。

任一步失败时不得发送远程请求。

### 4.2 最终化

- 成功：`succeeded`；
- 稳定的远程或协议失败：`failed` + 白名单错误码；
- timeout：`timed_out` + 稳定 timeout 错误码；
- 进程在发送后、最终化前终止：允许保留 `started`，不得猜测成功或失败。

最终化记录缺失必须显式失败，不得把业务路径报告为完整成功。

### 4.3 额度语义

额度在“远程发送资格已经取得”时消费，而不是在远程成功时消费。远程失败、
timeout、artifact 校验失败和业务 rollback 都不返还额度。

同一业务 Session 不再直接递增受管授权的 `used_calls`，避免后续提交用旧值
覆盖独立事务中的真实消费值。后续额度判断必须重新读取权威值或使用 recorder
返回的安全计数。

### 4.4 数据安全

持久化字段继续限制为：

- workspace / run / ordinal；
- 稳定工具名、状态、结果数量、耗时、稳定错误码；
- 不可逆输入摘要。

禁止保存 prompt、表达式正文、源代码、stdin、stdout/stderr、Wolfram 原文、
异常正文、凭据、内部 URL 或绝对路径。

## 5. 数据库约束

- `agent_tool_calls(agent_run_id, workspace_id)` 必须引用同一 Workspace 的
  `agent_runs(id, workspace_id)`；
- 同一 AgentRun 的 ordinal 唯一；
- 删除 AgentRun 时对应 Tool Call 级联删除；
- 两类授权的 `used_calls` 必须满足 `0 <= used_calls <= max_calls`；
- migration 必须验证既有数据后再增加约束，不得静默修正历史事实。

## 6. 验收

至少证明：

1. 五条接入路径在成功、失败和 timeout 后都留下正确 Tool Call；
2. 远程调用后业务 rollback，Tool Call 和 `used_calls` 仍存在；
3. recorder 预留失败时远程 stub 调用次数为零；
4. 两个并发消费者面对最后一个额度时只有一个成功；
5. retry 只能继承真实剩余额度，不能恢复已发送 attempt 的额度；
6. workspace/owner 错绑在 Postgres 层或 recorder 边界被拒绝；
7. API、受控 Compose 系统测试、浏览器 Gate 和 `git diff --check` 通过；
8. 受控测试不读取真实 secrets，不调用真实 provider/Judge0/Wolfram。

完成以上受控验证后，只运行每类一个低成本真实 pilot。pilot 事实可信后，才恢复
Spec 007 的正式远程样本矩阵。

## 7. 非目标

- 不提高 provider、repair、MCP、step 或 wall-time 预算；
- 不修改 Practice artifact、评分权威或队列状态；
- 不优化 C++ 生成质量或科学表达式质量；
- 不更换课程资料；
- 不新增 MCP capability；
- 不在本修正中自动推断长期 `started` 的最终结果；
- 不把真实远程 Gate 放入普通 PR。

## 8. 待人工 Gate

1. 接受远程 Tool Call 与额度消费使用独立短事务，业务 rollback 不返还额度；
2. 接受发送前原子消费额度并写入 `started`，成功提交后才发送远程请求；
3. 接受为 Agent Tool Call 增加 workspace、ordinal 和删除级联约束；
4. 接受该合同统一覆盖 Course、Practice 与 Tutor 的五条嵌入式远程工具路径；
5. 接受本修正只恢复事实可信度，不在同一 diff 中优化 C++ 或科学题质量。

以上五项已于 2026-07-30 获人工接受。
