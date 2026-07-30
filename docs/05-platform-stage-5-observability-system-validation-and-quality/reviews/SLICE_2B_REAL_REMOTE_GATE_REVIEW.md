# Slice 2B 真实 Provider / Judge0 / Wolfram Gate

日期：2026-07-30

状态：**真实 Gate 已执行但尚未达到正式样本量；窄修复后继续保持 failed**

> 2026-07-30 后续调查修正了本文件最初的两项归因：多个
> `AgentRun` 主要是 delivery retry 或失败路径另建 Run，并非并发 worker；
> Tutor 的 `retry_wait` 也不是终态。以下第 1-6 节保留首次运行快照，
> 当前结论以第 7 节为准。

## 1. 结论

本轮不是受控 fake 验证。调用链使用当前主开发栈、真实生成 provider、真实
Judge0 CE 和真实 Wolfram Cloud MCP，并从公开 API 的 Run、ProviderCall 与
AgentToolCall 安全投影收集证据。

真实远程能力已经运行，因此不再是 `remote_not_run`；但 Slice 2B 仍不能正式
收尾。Practice 生成出现重复 `AgentRun`、结构失败和额外 provider 调用，继续
执行 Spec 007 的完整重复次数会放大费用并污染分母。Codex 触发成本保护，停止
Practice 与题数曲线的后续批次。

## 2. 环境校验

- 主开发栈在 Gate 前按当前工作树重建 API、worker、Practice worker、
  Code Lab worker、MCP execution 与 capability probe。
- Postgres、Qdrant、Redis、storage 和 Tutor Skill 保持 ready。
- Gate 期间临时将 execution MCP 接到 Judge0 CE；每批结束后恢复此前配置。
- Wolfram capability projection 在真实 Gate 前为 ready。
- 未读取、打印或写入 `.env`、provider key、Wolfram key 或内部连接地址。
- 真实用户课程只用于产品检索；报告不保存课程原文、题干、答案或工具原文。

## 3. 有效记录

脱敏机器报告：

- `reviews/remote/slice2b-real-remote-20260730.json`
- 18 条已落盘记录：12 succeeded，6 failed。
- 36 次 ProviderCall；97,464 input tokens；55,376 output tokens。
- 36 次调用均缺少匹配的人民币价格快照，因此金额为 unknown，没有伪造 ¥0。

| 路径 | 结果 | 远程事实 |
|---|---:|---|
| Code Lab Python | 1/1 | Judge0 调用成功 |
| Code Lab Java | 1/1 | Judge0 调用成功 |
| Code Lab C++ | 1/1 | Judge0 调用成功 |
| 编程 Practice Python | 0/1 | 双 AgentRun；最终失败 |
| 编程 Practice Java | 0/1 | 双 AgentRun；发生 reference Tool；最终失败 |
| 编程 Practice C++ | 0/1 | 成本保护时取消 |
| required scientific Practice | 0/1 | 双 AgentRun；结构失败；Wolfram 零调用 |
| scientific 负对照 | 1/1 | 成功且 Wolfram 零调用 |
| Tutor code required | 5/5 | 每次真实 Code MCP 调用成功 |
| Tutor Wolfram required | 3/4 | 三次成功；一次 provider unavailable |
| Tutor 双工具负对照 | 0/1 | 工具零调用，但首次终态结构失败 |

另有一条 Tutor Wolfram 请求在客户端等待超时后于服务端成功。因为 Gate 未取得
该请求的同步回执，它没有补写进规定分母，避免把事后观察冒充正常 Gate 记录。

## 4. 阻断问题

### Blocker A：Practice 长调用产生重复 AgentRun

Python、Java 和 scientific Practice 均观察到同一业务请求对应两个 AgentRun。
第二个 Run 约在长 provider 调用期间出现。结果包括：

- provider 请求重复；
- ordinal、Tool 与最终错误分散到不同 Run；
- Run 与 Job 最终状态不一致；
- Java 单样本形成 4 次 ProviderCall；
- 真实成功率和成本分母失真。

在该问题关闭前，不得执行三语言各 5 次或 `1/3/5/10` 预算曲线。

### Blocker B：专业 Practice artifact 不稳定

- Python 编程题失败；
- Java 编程题失败；
- C++ 样本被成本保护取消；
- required scientific 样本以 `practice_artifact_schema_invalid` 失败；
- scientific required 样本没有形成 Wolfram 调用。

这同时复现了人工 smoke 报告的编程生成不稳定与科学题不调用 Wolfram。

### Blocker C：Tutor 终态并非稳定终态

负对照 Turn 曾先表现为 `invalid_agent_artifact`，随后同一 Turn 又出现成功 Run 并
改写为 succeeded。Gate 若在首次 terminal 立即结束，会记录错误结论。

远程 Gate 驱动已增加：

- 失败终态稳定观察窗口；
- 同一幂等键重试；
- 重复 AgentRun 计数；
- 业务失败优先于 `tool_call_missed` 的分类；
- 失败时非零退出码。

## 5. 成本保护

本轮没有继续执行以下高成本矩阵：

- Python、Java、C++ 各 5 次完整生成；
- scientific Practice required 5 次；
- Practice 负对照 3 次；
- `general_only / require_coding / require_science × 1/3/5/10`。

原因不是环境缺失，而是单个业务请求已经出现重复远程调用。继续运行只会重复证明
同一编排缺陷，并产生不可解释的成功率与费用。

## 6. 下一步

进入第三部分前，先形成一个窄修复 Slice，顺序固定为：

1. 修复 Practice lease/heartbeat/reconcile 导致的并发重复执行；
2. 锁定 Job、AgentRun、ProviderCall 的一对一 attempt 归属和稳定终态；
3. 修复编程 artifact（Python/Java/C++）结构与 reference validation；
4. 让 required scientific 样本可靠进入 Wolfram 请求漏斗；
5. 修复 Tutor terminal late transition；
6. 先以 1 次样本复验，再恢复完整远程分母和预算曲线。

在这些阻断项关闭并完成续跑前，Slice 2B 状态保持 **remote_gate_failed**。

## 7. 后续修复与复验

### 7.1 已关闭的产品/驱动问题

- Practice 失败路径复用并最终化同一 attempt 的运行事实，不再为同一 attempt
  创建第二条失败 Run；delivery retry 仍按新的 `attempt_number` 留痕。
- RQ timeout 与产品 10 分钟 wall budget 对齐，initial enqueue 与 reconciler
  都使用当前镜像验证。
- `require_coding` / `require_science` 进入生成 prompt 的强制合同；科学模式
  不再允许用普通本地题冒充 required science。
- provider 输出上限明确为每次调用上限。此前累计检查会在费用已产生后丢弃
  repair 结果，已按 ADR 005 移除；调用数、step、Tool 与 wall 上限不变。
- C++ prompt 固定 canonical declaration，并把实际 reference pass count 的安全
  摘要交给 repair；不暴露 tests、源码或 compiler 输出。
- required-science repair DTO 的 JSON schema 强制
  `needs_remote_verification=true` 与非空表达式。
- 真实 Wolfram MCP 返回的是 `<result>` 文本 envelope，而非 fake backend 的
  `{"verified": true}`。产品现在结构化解析独立 `# Result` 段，且只接受精确
  `True`；不会因 query 或说明文字中出现 `True` 而误判。
- Gate 将 `retry_wait` 视为非终态，只把同一 `(role, attempt_number)` 的重复
  Run 判为重复执行；可按语言做低成本 pilot，并允许负例次数为 0。
- Gate 报告的 Windows 原子替换增加有界重试；coding matrix 在付费 provider
  调用前必须先通过一次真实 C++ Code Lab probe。

### 7.2 聚焦与受控验证

- 预算、编程、科学、worker 聚焦集：`63 passed`。
- C++ prompt 与三语言 controlled compiler 基线：`25 passed`。
- required-science schema、Wolfram funnel 与相关修复路径：`25 passed`。
- Remote Gate contract、Wolfram、prompt 与 budget：`55 passed`。
- 完整 quality baseline、remote remediation、repair 与 worker 回归：
  `259 passed`。
- 受控 Compose 系统 Gate：`11 passed in 22.07s`，测试栈已清理。
- Python `py_compile` 与 `git diff --check` 通过。

另有一次 46 项集合得到 `45 passed / 1 failed`；唯一失败是从仓库根运行一个
使用 `alembic/...` 相对路径的既有 migration 静态测试，和本轮行为无关，
不计作通过。

### 7.3 真实低成本复验事实

| 样本 | 当前结果 | 说明 |
|---|---:|---|
| Practice Python | 1/1 succeeded | 一个 AgentRun；repair 后发布；真实 Judge0 |
| Practice Java | 1/1 succeeded | 一个 AgentRun；真实 Judge0 |
| Practice C++ | 0/3 pilots | 一次 repair 从 schema invalid 推进至 6/7 tests；后续一次仍为 6/7，一次三次 delivery attempt 均被 Judge0 unavailable 阻断 |
| required science（热化学） | 0/多次 pilot | 已真实进入 Wolfram；reference 与 repair 均未得到 `True` |
| required science（泰勒公式） | 0/1 pilot | 同样未通过远程等价验证 |
| science 负例 | repeated succeeded | 发布普通题且 Wolfram 零调用 |

真实 Python pilot 证明累计 token 修复有效。C++ 最近一次失败是公共 Judge0 CE
连续不可用，不能继续用付费 provider 重试来探测基础设施；新增 probe 会在模型调用
前阻断。科学两份资料都能触发 required 路径，但生成的 reference 经一次 repair
仍无法被 Wolfram 验证，因此这已不是“题太简单所以不调用”的问题，而是科学
reference 质量问题。

### 7.4 仍未关闭

1. C++ 尚无修复后的稳定成功分母；需 Judge0 probe 先通过，再恢复 5 次正式样本。
2. scientific Practice 确实调用 Wolfram，但两份真实课节的 reference/repair
   仍未通过；不得把 Tool 成功返回非 `True` 当作验证成功。
3. 失败事务会回滚 `AgentToolCall`，因此失败报告可能显示 `tool_called=false`；
   成功事务事实完整，但失败漏斗的 durable Tool fact 仍需独立 ADR/实现。
4. Spec 007 规定的每语言 5 次、required Tool 各 5 次、负例各 3 次尚未完成；
   当前结果是 remediation pilots，不是正式成功率。
5. ProviderCall 均无人民币价格快照，金额仍为 unknown，不能写成 ¥0。

因此当前状态仍是 **remote_gate_failed**，但 `remote_not_run` 已关闭。继续正式
分母前，应先解决 durable Tool fact，并在 Judge0 probe green 时才允许 coding
provider matrix 开始。
