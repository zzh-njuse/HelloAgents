# Stage 5 Part 2 Slice 2A：Provider Call 持久化修复任务包

状态：可执行

日期：2026-07-28

## 1. 目标

修复真实 Tutor timeout 系统测试发现的事务问题：provider 请求已经发生并由
recorder 最终化，但业务 worker rollback 后 Provider Call 被一并删除。

实现后必须满足：

- Provider Call 是独立持久化的外部请求事实；
- 业务 artifact、Turn 或 Job 回滚不能删除已发生的调用事实；
- 请求前 `started` 已提交，写入失败时不得发送请求；
- 五条现有 token 计费链使用同一事务语义；
- 不改变 provider 调用次数、业务 artifact、重试预算或公开读取合同。

权威合同：

- [Spec 003](specs/003-provider-call-business-instrumentation.md)
- [ADR 002](adr/002-provider-call-recording-lifecycle-and-rag-owner.md)
- [Spec 006](specs/006-controlled-system-tests-and-ci-gates.md)
- [ADR 004](adr/004-durable-provider-call-facts-across-business-rollback.md)

ADR 004 在本问题上取代 ADR 002 的“recorder 与业务事务同生共死”限制。其他
ADR 002 合同继续有效。

## 2. 已复现证据

Codex 已建立并运行真实受控路径：

```text
HTTP API -> Redis -> 独立 RQ worker -> Postgres -> Qdrant -> HTTP provider stub
```

当前结果：

- Tutor success：通过，产生 `plan/answer`；
- Tutor repair：通过，产生 `plan/answer/repair`；
- Tutor timeout：Turn 为 `retry_wait`，AgentRun 为 `failed`；
- timeout recorder 在抛出前形成 `timed_out/provider_timeout`；
- `tutor_workers.run_tutor_turn()` rollback 后最终 Provider Call 数量为 0。

现有系统测试位于 `tests/system/test_tutor_vertical.py`。该 timeout 断言是正确
产品合同，不得删除、skip、xfail、放宽为 0 条或改成只检查 helper。

## 3. 环境与已知工作区

- Windows PowerShell；
- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`；
- 当前分支：`main`；
- Python：仓库现有 `.venv`；
- 产品 API：`apps/api`；
- Codex 已在工作区建立 Slice 2A Compose、stub、system test、CI、Playwright
  和规划文档，这些是合法未提交改动；
- `.tmp/`、`artifacts/` 是未知内容，禁止读取、修改、删除或加入 Git；
- 不安装依赖，不调用真实 provider，不运行 OCR；
- 不 commit，不 push。

开始前完整读取根 `AGENTS.md`、`docs/README.md`、四份仓库方向文档、
GLM handoff workflow、本任务包及四份权威合同，然后检查
`git status --short --branch`。不得回滚或覆盖 Codex 和用户的现有改动。

## 4. 允许修改

最小范围允许：

- `apps/api/learn_platform_api/services/provider_call_recorder.py`；
- 五条链建立和使用 AgentRun/RagAnswerTrace 的现有 orchestration service；
- 五条链的 worker，仅在建立持久 owner 或正确完成失败状态确有必要时；
- recorder 和五条链直接相关 focused tests；
- 本任务 handback。

原则上禁止：

- migration、ORM schema、Provider Call 读取 API、质量成本聚合和 Web；
- `compose.system-test.yml`、`tests/system/`、`.github/`、Playwright 和运行脚本；
- prompt、artifact schema、评分权威、队列名称、重试预算、错误码；
- provider adapter 协议、MCP、Judge0、Wolfram、部署配置和依赖；
- 大范围格式化或顺手重构。

若可靠实现必须修改 schema、公开 API、重试合同或系统测试基础设施，立即停止并
写入 handback，不自行扩大范围。

## 5. 强制事务合同

### 5.1 最小 owner

每次 outbound request 前，Provider Call 引用的 AgentRun 或 RagAnswerTrace
必须已经提交并可由另一数据库 Session 查询。

允许把 owner 建立拆成明确的前置事务，但只能提交最小运行事实。不得提前提交
回答、课节、练习、评分、evidence 或其他半成品业务 artifact。

### 5.2 独立 recorder 事务

共享 recorder 统一管理短生命周期独立 Session：

1. 在独立事务中校验 owner/workspace、分配 ordinal、选择历史价格并提交
   `started`；
2. 只有 `started` 提交成功后才调用 provider；
3. provider 返回或抛出受控异常后，在独立事务中按已创建 ID 最终化；
4. 原业务 Session 的 commit/rollback 不得删除或覆盖这条事实。

不得在异常处理中 commit 原业务 Session，因为它可能包含无效半成品。不得只为
Tutor 添加 rollback 后补写分支；五条链必须复用同一 recorder 语义。

### 5.3 一致性与失败

- 每次真实 request attempt 恰好一条 Provider Call；
- ordinal 仍为 owner 内从 0 开始的单调唯一值；
- phase、provider/model、价格快照、usage、latency 和稳定错误码沿用现有合同；
- timeout 为 `timed_out/provider_timeout`；
- provider 成功返回后 artifact 校验失败，该调用仍保持 `succeeded`；
- finalize 写入失败不能被报告为完整成功；
- 进程强杀可以留下 `started`，本任务不猜测最终状态；
- 不增加 provider retry 或调用次数；
- 不写 prompt、question、answer、response 或异常正文。

### 5.4 Session 隔离

不得让独立 recorder Session 接管、关闭、rollback 或 commit 调用方 Session。
不得把一个 Session 中仍未提交的 ORM 实例直接交给另一 Session；跨事务只传递
稳定 ID 和白名单标量。

## 6. 五条链要求

统一核对：

- Course generation；
- Tutor；
- Practice generation；
- Practice grading；
- RAG Answer。

每条链至少证明：

- owner 在首次 provider request 前可被独立 Session 查询；
- 正常调用仍产生正确 phase/ordinal/usage；
- 实际存在的 repair 产生新 Provider Call；
- 一个受控失败或 timeout 在业务 rollback 后仍保留最终 Provider Call；
- provider stub 调用次数与修复前合同一致；
- AgentRun/Job/Turn/Trace 最终状态和重试预算不变。

禁止使用源码字符串检查或直接调用 recorder 代替真实 orchestration 行为。

## 7. 最低测试

### Recorder focused

- `started` 已提交后才调用 stub；
- start commit/约束失败时 stub 调用数为 0；
- success、failed、timeout、cancel 最终化；
- 调用方 rollback 后事实仍存在；
- 调用方 Session 不被独立 recorder 改变；
- finalize 失败不会吞掉或伪装业务结果；
- 敏感字段继续排除。

### 真实 orchestration

- 保留并通过现有五条链行为测试；
- 补充五条链业务入口或真实 service orchestration 的 rollback 持久化断言；
- Tutor 必须覆盖 timeout；
- 至少一条成功后 artifact validation 失败的反例，证明调用仍为
  `succeeded`；
- workspace/owner 错绑继续由数据库拒绝。

### 系统测试

不要修改 `tests/system/`。实现完成后可运行任务包第 8 节的受控命令，目标是
现有三个 Tutor 测试全部通过。

## 8. 验证顺序

先运行窄测试，避免无意义全量消耗：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_provider_call_chain_behavior.py
```

再运行 Provider Call、AgentRun 和五条链直接相关回归。根据实际文件名列出真实
执行命令，不得用“相关测试通过”代替。

若 Docker 可用，最后运行：

```powershell
.\scripts\system-test.ps1
```

该命令必须得到 Tutor success、repair、timeout 三项通过，并在结束后清理隔离
容器和 volumes。若镜像环境不可用，报告原始环境原因；不得把未运行写成通过。

最后运行：

```powershell
git diff --check
```

本任务不需要 Web lint/build，不运行 OCR。

## 9. 停止条件

遇到以下任一情况立即停止对应实现并报告：

- 必须新增 migration 或修改 Provider Call schema；
- 无法在不提交业务半成品的情况下先提交 owner；
- 独立 Session 会改变调用次数、重试预算或错误状态；
- 五条链无法共享同一 recorder 事务合同；
- 现有未提交改动与任务范围冲突；
- 真实 secrets 或用户资料成为测试前提。

不得用放宽测试、增加测试模式、硬编码问题文本或捕获后静默忽略来绕过。

## 10. 交回

生成：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2A_DURABLE_PROVIDER_CALL_GLM_HANDBACK.md`

包含：

- 修改文件；
- owner 前置持久化和 recorder 独立事务设计；
- 五条链逐项接入位置；
- provider 调用次数不变证据；
- success/repair/timeout/rollback 的数据库结果；
- 实际测试命令和逐项结果；
- 未运行项及原因；
- 敏感字段排除确认；
- 已知风险或合同冲突；
- 未 commit、未 push、未运行 OCR 的确认。

完成本任务后停止，不修改系统测试基础设施，不进入 Slice 2B。
