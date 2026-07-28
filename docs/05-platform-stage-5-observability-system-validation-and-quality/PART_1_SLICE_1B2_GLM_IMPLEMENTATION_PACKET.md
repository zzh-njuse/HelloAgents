# Stage 5 Part 1 Slice 1B-2：GLM 实现任务包

状态：可执行
日期：2026-07-27

## 1. 目标

在一个统一实现任务中，把 Provider Call 事实接入：

- Course generation；
- Tutor；
- Practice generation；
- Practice grading；
- RAG Answer。

权威合同：

- [Spec 003](specs/003-provider-call-business-instrumentation.md)
- [ADR 002](adr/002-provider-call-recording-lifecycle-and-rag-owner.md)
- [Spec 002](specs/002-provider-call-cost-foundation.md)
- [ADR 001](adr/001-provider-call-and-cny-cost-facts.md)

遇到合同冲突、调用次数变化或必须改变既有业务事务/重试合同，停止并写入
handback，不自行扩展。

## 2. 运行环境与基线

- Windows PowerShell
- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- Python：仓库现有 `.venv`
- API：`apps/api`
- 当前分支：`main`
- Slice 1B-1 的 migration `0024` 和相关代码尚在工作区、未 commit；这是本任务
  的合法基线，不得回滚、重建或覆盖
- 新 migration 只能是 `0025`，`down_revision="0024"`
- Postgres migration/外键测试只使用隔离、可丢弃数据库
- 不安装依赖，不修改 Compose，不读取或改动 `.tmp/`、`artifacts/`
- 不 commit，不 push，不运行 OCR，不调用真实 provider

开始前完整读取根 `AGENTS.md`、Playbook、GLM handoff workflow、本任务包及四份
权威合同，并检查 `git status --short --branch`。

## 3. 允许修改

按最小范围允许：

- `apps/api/learn_platform_api/db/models.py`
- `apps/api/alembic/versions/0025_add_rag_provider_call_owner.py`
- 新增共享 Provider Call recorder service
- Course/Tutor/Practice/RAG Answer 当前真实 orchestration service
- 与上述调用链直接相关的 focused tests
- Stage 5 handback

禁止修改公开 API/Web、prompt 内容、artifact schema、评分权威、队列状态、
重试预算、MCP、依赖或部署配置。不得顺手重构大文件。

## 4. Schema：RAG owner

在 `0025` 和 ORM 中同步实现：

- `provider_calls.rag_answer_trace_id` 可空；
- RagAnswerTrace 增加命名明确的冗余 `UNIQUE(id, workspace_id)`；
- 复合外键
  `(rag_answer_trace_id, workspace_id) -> rag_answer_traces(id, workspace_id)`，
  `ON DELETE CASCADE`；
- `agent_run_id` 与 `rag_answer_trace_id` 最多一个非空；
- 两者均空的 Workspace-only 调用仍合法；
- RAG owner 内 `(rag_answer_trace_id, ordinal)` 条件唯一；
- downgrade 先移除 Provider Call 新约束/列，再移除 RagAnswerTrace 冗余唯一约束；
- 不削弱 `0024` 已有 Workspace 和价格绑定约束。

以真实隔离 Postgres 验证 upgrade/downgrade、跨 Workspace 反例、owner 互斥、
ordinal 唯一和删除级联。

## 5. 共享 recorder

只实现一套 recorder，由拥有 DB、Workspace 和 owner 的 orchestration 调用。
低层 HTTP helper 不得猜测 owner。

recorder 必须：

- 在真实请求发送前创建 `started` Provider Call 并 `flush`；
- 写入实际 provider/model、owner、单调唯一 ordinal、稳定 phase、started_at；
- 选择相同 provider/model 且 `effective_at <= started_at` 的最新价格快照；
- 无价格时保持 snapshot NULL；
- 约束或 flush 失败时不调用 provider stub；
- 返回后记录 succeeded、usage、latency、completed_at；
- HTTP/provider/解析错误记录 failed；
- timeout 记录 timed_out；
- 明确取消记录 canceled；
- 只保存稳定 error code，不保存异常正文；
- 不估算缺失 usage，不持久化派生成本；
- 不 commit 或擅自改变当前业务事务边界。

异常最终化不得吞掉原业务异常，也不得把失败伪装成功。若当前代码没有明确取消
路径，只覆盖真实存在的取消异常，不新增虚构分支。

## 6. 五条调用链接入

逐个定位真实 outbound attempt，并在拥有 owner 的 `provider_step` 或等价
orchestration 边界接入：

- Course generation：绑定当前 course AgentRun；
- Tutor：绑定当前 tutor AgentRun；
- Practice generation：绑定 exercise-author AgentRun；
- Practice grading：绑定 answer/scientific grader AgentRun；
- RAG Answer：绑定当前 RagAnswerTrace。

initial、plan、answer、generation、grading、repair/retry 等每个真实请求必须是
独立 Provider Call。不得增加、合并或删除现有 provider 请求。

建立集中 phase allowlist。phase 只表达低基数目的，不包含动态 ID、正文或异常。
在 handback 列出每条链实际 phase。

保留 AgentRun、Tutor Turn、Practice Job、RagAnswerTrace 现有状态、step/token
聚合和错误合同，不用 Provider Call 反向重算它们。

RAG embedding、Wolfram、Code Lab 和 MCP 不接入。

## 7. 最低测试

### Recorder

- started 先于 provider stub；
- success、failed、timeout，以及代码中真实存在的 cancel；
- 单维/双维 usage 缺失保持 NULL；
- 历史最近价格、排除未来价格、无价格；
- flush/约束失败时 provider stub 调用次数为零；
- 不保存敏感正文。

### 业务链

每条链至少以真实 service/orchestration + provider stub 覆盖：

- 正常调用生成正确 owner/provider/model/phase/ordinal；
- 实际存在的 repair/retry 产生第二条事实；
- provider stub 调用次数与改动前一致；
- 既有 Run/Turn/Job/Trace 聚合和状态回归；
- 失败路径留下正确 Provider Call 状态；
- 不调用真实 provider。

### 数据库

- `0024 -> 0025 -> 0024` 隔离 Postgres round-trip；
- RAG 同 Workspace 成功、跨 Workspace 失败；
- AgentRun/RAG owner 互斥；
- RAG owner ordinal 唯一；
- 删除 RagAnswerTrace/Workspace 的级联；
- `0024` 的 Workspace 隔离和价格错绑反例继续通过。

不要使用源码字符串检查代替业务行为测试。测试数量应围绕风险，不为追求数量
重复同一断言。

## 8. 建议验证

先运行新增 focused tests，再运行直接相关既有回归。至少包括：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q <新增 focused tests>
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_agent_run_api.py `
  <Course/Tutor/Practice/RAG 直接相关既有测试>
git diff --check
```

真实 Postgres 测试必须明确指向随机 throwaway 数据库并用后删除。若环境不可用，
必须明确 skip 和 handback 说明，不能用 SQLite 冒充。

不要运行 API 全量、Web build 或 OCR，除非直接相关回归暴露跨模块问题。

## 9. 交回

生成 `PART_1_SLICE_1B2_GLM_HANDBACK.md`，包含：

- 修改文件和各链接入点；
- migration/owner/价格选择实现；
- phase allowlist；
- 每类状态与 usage 映射；
- 各链 provider stub 调用次数不变的证据；
- 实际命令和逐项结果；
- 未运行项及原因；
- 已知风险、合同疑点；
- 敏感字段排除确认；
- 未 commit、未 push、未运行 OCR 的确认。

完成全部五条链后停止，不进入 1B-3。
