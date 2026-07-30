# Stage 5 Part 2 Slice 2A：Provider Call 持久化验收修正包

状态：可执行

日期：2026-07-28

## 1. 背景

主体实现方向成立，Codex 独立运行 `.\scripts\system-test.ps1` 已得到 Tutor
success、repair、timeout 三项通过。

本轮只关闭独立验收发现的三个阻断项和一个无效测试证据。不得重做 ADR 004
方案，不得进入其他 Slice。

权威输入：

- `PART_2_SLICE_2A_DURABLE_PROVIDER_CALL_GLM_PACKET.md`
- `adr/004-durable-provider-call-facts-across-business-rollback.md`
- `specs/003-provider-call-business-instrumentation.md`
- `specs/006-controlled-system-tests-and-ci-gates.md`

## 2. Fix 1：RAG Trace 最终状态必须持久化

当前 `answer_question()` 已提前 commit 最小 `RagAnswerTrace(status=running)`，
但成功和异常分支只 `flush()`。路由不负责 commit，因此请求结束后最终状态会被
rollback，数据库永久留下 `running`。

修正要求：

- 成功时持久化 Trace 的 `succeeded`、usage、latency、answer hash 和
  completed_at；
- 失败时持久化 Trace 的 `failed`、稳定 error_code、安全 error_message 和
  completed_at；
- 不保存回答正文、异常正文或其他敏感字段；
- Provider Call 与 Trace owner 继续保留正确关联；
- 不把 router 改成无条件 commit；
- 不重复创建第二条 Trace；
- Trace 最终化失败不得吞掉原始 provider/业务异常，也不得伪装成功。

新增真实 service/API 行为测试：

- RAG 正常回答后以新 Session 查询 Trace，状态为 `succeeded`；
- RAG timeout/受控 provider 失败后以新 Session 查询同一 Trace，状态为
  `failed`，对应 Provider Call 保持最终失败事实；
- 不允许只检查当前 Session 中尚未提交的 ORM 值。

## 3. Fix 2：Recorder 最终化不得静默缺失

当前 `succeed()`、`fail()`、`timeout()`、`cancel()` 在按 `call_id` 找不到
Provider Call 时直接返回。

修正要求：

- `_call_id is None` 表示 recorder 尚未 start，继续保持现有兼容行为或使用明确
  的调用顺序错误，但必须由测试锁定；
- 已有 `_call_id`，独立 Session 却找不到记录时，必须抛出固定、低基数异常，
  例如 `RuntimeError("provider_call_finalize_missing")`；
- commit/数据库异常自然向上传递，不能吞掉；
- `record_provider_call()` 在 provider 成功但最终化失败时不得返回成功结果；
- provider 已经抛出原始异常且失败最终化又失败时，不得静默丢失最终化故障。
  保留原始异常因果链或使用 `raise ... from ...`，不得持久化异常正文。

最低反例：

- start 后从另一 Session 删除该 Provider Call，再调用四种 finalizer，均明确失败；
- provider stub 成功返回、随后 finalizer 缺失时 wrapper 不返回成功；
- 不通过 monkeypatch finalizer 为任意异常来代替“记录真实缺失”场景。

## 4. Fix 3：Course owner commit 只能提交最小 owner

`_execute_lesson_generation()` 当前在创建 AgentRun 前可能先创建
`JobToolAuthorization`，随后 `db.commit()` 会把授权行和 AgentRun 一起提交。
这违反 ADR 004 的最小 owner 边界并改变失败/重试后的授权事实。

修正要求：

- 首次 provider request 前独立 Session 能查询 AgentRun；
- owner 前置 commit 不得顺带提交新建的 JobToolAuthorization、LessonVersion、
  Citation 或其他业务半成品；
- science authorization 的原有创建、预算和 rollback/重试语义保持不变；
- 不删除 science capability；
- 不通过提前额外 commit authorization 绕过问题。

可选择在创建任何业务半成品之前建立并提交 AgentRun，随后再创建授权；也可使用
同等清晰且可测试的顺序。不得对整个 service 做无关重构。

新增反例：

- science authorization 条件成立；
- AgentRun owner 已能被独立 Session 查询；
- 在首次 provider 调用前或调用失败后执行业务 rollback；
- 新建 authorization 不应因为 owner commit 被意外持久化；
- provider 正常路径的 authorization 行为继续符合既有合同。

## 5. Fix 4：真实 start commit/FK 失败测试

现有名为 commit/constraint failure 的测试仅使用非法 phase，异常发生在打开
Session 之前，不能证明独立事务 commit 失败时 provider 不会被调用。

修正要求：

- 保留非法 phase 测试，但改为准确名称；
- 新增真实数据库失败：使用不存在的 AgentRun/RagAnswerTrace owner，或可靠的
  workspace/owner FK 错绑，使 `started` 的独立事务在 flush/commit 时失败；
- 断言 provider stub 调用数为 0；
- 使用真实 ORM/数据库约束，不检查源码字符串；
- Postgres 正式约束应至少有一项隔离 Postgres 反例；SQLite focused test 可作为
  快速补充，不能冒充 Postgres 证据。

## 6. 允许修改

仅允许：

- `services/answers.py`
- `services/provider_call_recorder.py`
- `services/course_generation.py`
- 直接相关 focused tests
- 必要时更新本轮 handback

原则上禁止修改其他产品文件、migration、ORM schema、公开响应 schema、Web、
Compose、`tests/system/`、CI、Playwright、依赖和任务脚本。

禁止读取或修改 `.tmp/`、`artifacts/`。不 commit、不 push、不运行 OCR、不调用
真实 provider。

## 7. 验证

先运行新增的四组窄测试，再运行：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_provider_call_chain_behavior.py
```

再运行 RAG Answer、Course generation、Provider Call Postgres 和 AgentRun 的直接
回归，handback 必须列出真实文件与逐项结果。

最后运行：

```powershell
.\scripts\system-test.ps1
git diff --check
```

系统测试必须仍为 Tutor 三项通过并完成容器/卷清理。Docker 环境真实不可用时
报告原因，不得写成通过。

## 8. 交回

更新：

`PART_2_SLICE_2A_DURABLE_PROVIDER_CALL_GLM_HANDBACK.md`

逐项说明 Fix 1-4 的修改、反例、测试命令和结果。完成后停止，不运行 OCR，
不进入 Slice 2B。
