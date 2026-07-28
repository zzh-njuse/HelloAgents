# Spec 003：Provider Call 业务调用链接入

状态：已接受（2026-07-27）

日期：2026-07-27

适用范围：Platform Stage 5 第一部分 Slice 1B-2

## 1. 目标

把 Slice 1B-1 已建立的 Provider Call 事实接入现有 token 计费生成链：

- Course generation；
- Tutor；
- Practice generation；
- Practice grading；
- RAG Answer。

本 Slice 是一个统一实现任务，不再拆成多个子 Slice。它只记录现有真实调用，
不改变 prompt、生成/评分合同、重试预算、队列状态或用户界面。

## 2. 不在范围

- RAG embedding；
- Wolfram、Code Lab 或其他 MCP 工具；
- 新 provider、新模型、新重试或 fallback；
- 成本读取 API、聚合、Web 或 dashboard；
- 历史 Provider Call backfill；
- 多币种、汇率、折扣或账单；
- 上传原文、prompt、回答、evidence、原始响应或异常正文的持久化；
- 进程被强杀后 `started` 事实的恢复策略。

## 3. 共享记录合同

所有链路复用同一个 Provider Call recorder，不得复制五套写入逻辑。

每一次实际 outbound provider request attempt 对应一条 Provider Call，包括
initial、repair 和现有合同允许的 retry。逻辑步骤不能覆盖前一次调用。

### 3.1 发送前

只有请求已完成本地校验、即将发送时才建立记录。API key 缺失、prompt 构建失败
或其他发送前错误不得伪造 Provider Call。

发送前必须：

- 使用调用所属 Workspace；
- 绑定当前 AgentRun；RAG Answer 绑定当前 RagAnswerTrace；
- 从本次调用配置快照 provider/model；
- 分配 owner 内单调且唯一的 ordinal；
- 写入稳定 phase、`started` 和开始时间；
- 按第 5 节选择价格快照；
- 在发起网络请求前至少 `flush`，使约束先于外部副作用得到验证。

本 Slice 不承诺进程强杀时 `started` 一定独立提交；不得为此擅自改变现有业务
事务边界。正常返回和受控异常必须持久化最终状态。

### 3.2 返回与异常

- provider 返回可用响应：`succeeded`；
- HTTP/provider/响应解析错误：`failed`；
- 明确 timeout：`timed_out`；
- 明确取消：`canceled`；
- 记录完成时间和非负 latency；
- 只保存稳定、低基数 error code，不保存异常正文；
- provider 未明确报告某一维 token 时，该维保持 `NULL`；
- 不按文本长度、max token 或其他启发式补 usage。

业务 artifact 后续校验失败不反向改写一次已经成功返回的 Provider Call。若现有
repair 产生新请求，则 repair 是新的 Provider Call。

### 3.3 既有聚合

AgentRun、Tutor Turn、Practice Job 和 RagAnswerTrace 的既有状态、step/token
聚合继续按原合同更新。Provider Call 是更细的事实，不取代或反向重算既有字段。

## 4. Owner 与 Workspace

Course、Tutor、Practice generation/grading 使用现有 AgentRun owner。

RAG Answer 当前没有 AgentRun。migration `0025` 为 Provider Call 新增可空
`rag_answer_trace_id`，并满足：

- `(rag_answer_trace_id, workspace_id)` 复合外键强制 Workspace 一致；
- RagAnswerTrace 增加仅供复合外键引用的冗余
  `UNIQUE(id, workspace_id)`；
- 删除 RagAnswerTrace 时级联删除其 Provider Call；
- `agent_run_id` 与 `rag_answer_trace_id` 最多一个非空；
- 两者都为空时继续允许 Workspace-only 事实；
- RAG owner 内 `(rag_answer_trace_id, ordinal)` 唯一；
- 不把 RAG Answer 强行改造成 AgentRun。

## 5. CNY 价格快照选择

记录器按本次调用的 provider/model 和 `started_at` 查询：

```text
provider/model 完全相同
effective_at <= started_at
按 effective_at 倒序取第一条
```

匹配时绑定该不可变快照；没有匹配时保持
`provider_rate_snapshot_id=NULL`。不得读取未来价格、猜测别名或使用当前价格
改写历史调用。Slice 1B-2 不负责创建或预置价格。

## 6. Phase 与 ordinal

- phase 必须是代码内集中维护的稳定低基数字符串；
- phase 表达调用目的，例如 plan、answer、generation、grading、repair；
- ordinal 表达同一 owner 内真实请求顺序；
- repair/retry 使用新的 ordinal，不覆盖原记录；
- 不把题目、课程、用户文本、异常或动态 ID 放进 phase。

实现任务包必须列出各链实际 phase allowlist，并由测试锁定；不得借 phase
重构现有业务编排。

## 7. 安全与失败不变量

- Provider Call 不保存 prompt、message、question、answer、evidence、response、
  payload、raw error、provider key、内部 URL 或绝对路径；
- 跨 Workspace owner 绑定必须由数据库拒绝；
- 错 provider/model 价格绑定继续由数据库拒绝；
- Provider Call 写入失败时不得继续发送 provider 请求；
- Provider Call 最终化失败不得被静默吞掉或伪装为完整成本事实；
- 观测写入不得增加 provider 调用次数或改变重试预算。

## 8. 最低验证

- 共享 recorder：发送前记录、成功、失败、timeout、取消和 usage 缺失；
- 价格选择：历史最近值、未来价格排除、无价格保持 unknown；
- 每条业务链至少覆盖 initial 与其实际存在的 repair/retry；
- 证明真实 provider stub 的调用次数未增加；
- AgentRun/RagAnswerTrace owner、ordinal 和 Workspace 隔离；
- `0024 -> 0025 -> 0024` 隔离 Postgres round-trip；
- RagAnswerTrace 删除级联及 Workspace 删除回归；
- Provider Call 写入失败时 provider stub 未被调用；
- 现有 Course、Tutor、Practice、RAG focused regression；
- 禁止字段和日志脱敏检查；
- 不调用真实 provider。

测试应经过公开业务 service 或真实 orchestration 边界，不能只检查源码字符串或
只测试一个脱离业务链的 helper。

## 9. 交付与 Gate

- GLM 一次实现全部五条调用链并生成一个 handback；
- Codex 只做关键合同与风险验收，不重复无意义的全量分析；
- 本 Slice 不单独运行 OCR；
- 1B-1、1B-2、1B-3 完成后统一执行白名单分块 OCR；
- 出现错账、跨 Workspace、敏感信息或调用次数变化时立即停止，不等待 OCR。

2026-07-27 已接受五条调用链统一实现、RagAnswerTrace owner、价格快照选择
规则，以及不为进程强杀改变既有事务边界。
