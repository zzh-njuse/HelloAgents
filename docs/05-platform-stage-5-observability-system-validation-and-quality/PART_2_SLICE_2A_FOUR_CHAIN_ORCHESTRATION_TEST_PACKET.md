# Stage 5 Part 2 Slice 2A：其余四条 Provider Call Orchestration 测试包

状态：可执行

日期：2026-07-29

## 1. 目标

Tutor 已由 Codex 建立真实 HTTP、Redis/RQ worker、Postgres、Qdrant 和 HTTP stub
纵向测试。本任务只补齐以下四条链的 Provider Call orchestration 证据：

- Course generation；
- Practice generation；
- Practice grading；
- RAG Answer。

这是**测试任务**。现有产品行为和 Provider Call 持久化实现已经通过验收，本轮
禁止修改产品代码。

权威合同：

- `specs/006-controlled-system-tests-and-ci-gates.md` §4.2；
- `specs/003-provider-call-business-instrumentation.md`；
- `adr/004-durable-provider-call-facts-across-business-rollback.md`；
- `PART_2_SLICE_2A_ACCEPTANCE_TEST_FIX_PACKET.md`。

## 2. 边界

仅允许：

- 在 `apps/api/tests/` 新增一个明确命名的 Postgres orchestration 测试文件；
- 必要时复用现有测试 helper，但不得改变全局 fixture 语义；
- 更新 Slice 2A handback。

禁止修改：

- `apps/api/learn_platform_api/**`；
- 既有 migration、schema、公开 API 和 Web；
- `tests/system/`、Compose、CI、Playwright 和运行脚本；
- prompt、artifact、评分、重试、队列和 provider adapter；
- `.tmp/`、`artifacts/`。

不安装依赖，不调用真实 provider，不运行 OCR，不 commit，不 push。

## 3. 测试层级

四条链必须从现有公开业务 service 或完整 orchestration 入口进入。允许：

- fixture 直接准备所需 Workspace、Course、Lesson、Practice 等权威数据库事实；
- monkeypatch 最低层 provider HTTP、retrieval、MCP/编译器外部边界；
- 使用确定性的合法/非法 provider 响应驱动 normal、repair、timeout。

禁止：

- 直接调用 `ProviderCallRecorder` 或 `record_provider_call()` 作为最终证据；
- 在测试中手工创建 ProviderCall；
- 手工复制 orchestration 的 phase、commit 或状态更新；
- 只检查 mock 调用参数或源码字符串；
- 用 SQLite 冒充正式事实来源。

所有最终事实必须使用新的 Postgres Session 查询。

## 4. Postgres Gate

使用仓库现有隔离 Postgres fixture/throwaway database 模式：

- 每次运行使用随机、可丢弃数据库；
- 执行真实 migration 或与现有 Postgres 测试一致的 schema 初始化；
- Postgres 不可达时，在本任务声明的 Gate 中必须失败，不得 skip；
- 不触碰开发数据库；
- 测试结束删除临时数据库；
- handback 写明连接来自测试环境但不得输出密码或内部连接细节。

不要另建一套数据库管理框架，优先复用现有
`test_provider_call_*_postgres.py` 的 fixture。

## 5. 每条链的最低场景

### 5.1 Course generation

经过真实 `execute_generation()` 或当前等价 orchestration：

- normal：产生预期 plan/generation 阶段；
- repair：首次 artifact 无效、修复响应合法，产生独立 repair 调用；
- 至少一个受控 provider failure 或 timeout；
- 查询最终 AgentRun 和 ProviderCall。

### 5.2 Practice generation

经过真实 `execute_generation()`：

- normal：产生 plan/generation；
- repair：首次练习 artifact 不合法，repair 后成功；
- 最终查询 exercise-author AgentRun 和 ProviderCall；
- 不改变 Practice artifact、题型或重试预算。

### 5.3 Practice grading

经过真实 `execute_grading()`：

- 选择无需真实 Judge0/Wolfram 的代表性评分路径；
- normal：产生 grading；
- repair：首次评分 artifact 无效，repair 后成功；
- 最终查询 answer-grader AgentRun 和 ProviderCall；
- 不把 fake compiler/science 结果冒充真实远程工具 Gate。

### 5.4 RAG Answer

经过真实 `answer_question()`：

- normal：产生 answer 并绑定 RagAnswerTrace；
- repair：首次 answer artifact 无效、repair 后成功；
- timeout：低层 HTTP helper 真实收到 `httpx.TimeoutException`；
- Trace 与 ProviderCall 最终状态均从新 Postgres Session 查询。

可以复用已经通过真实性验收的 RAG service 测试构造，但本任务必须把正式
Postgres 事实纳入统一四链 Gate，不能仅引用 SQLite 结果。

## 6. 每个场景的共同断言

最终从 Postgres 查询并断言：

- ProviderCall.workspace_id 等于业务 Workspace；
- owner 正确：前三条绑定对应 AgentRun，RAG 绑定 RagAnswerTrace；
- owner 互斥；
- ordinal 从 0 开始、单调、无重复；
- phase 序列与真实 outbound attempt 一致；
- normal/repair 的调用数与 provider stub 实际调用数一致；
- provider/model 来自实际测试配置；
- usage 只取 stub 明确报告值；
- timeout 为 `timed_out/provider_timeout`；
- 业务 Run/Trace 使用既有稳定状态与错误码；
- ProviderCall 表不存在 prompt、回答、用户答案、异常正文、key、内部 URL 或
  绝对路径字段。

禁止断言固定随机 UUID 大小顺序。

## 7. 控制测试规模

目标是少量高价值参数化测试，而不是复制几十个近似用例。建议：

- 四条链各一个 normal/repair 参数化测试；
- RAG 单独一个 timeout；
- 如 Course/Practice 共用 timeout 合同已有充分 focused 证据，不重复三遍；
- 总数建议 5-8 项。

每个测试必须能在破坏对应 phase、owner、recorder 接入或 timeout 分类时失败。

## 8. 验证

先只运行新增文件，再运行直接回归：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/<新增四链 Postgres 测试文件>

.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_chain_behavior.py `
  apps/api/tests/test_acceptance_evidence_rag_trace.py `
  apps/api/tests/test_acceptance_evidence_course_owner.py `
  apps/api/tests/test_acceptance_evidence_wrapper.py

git diff --check
```

若本地 `.venv` 不可执行，可使用仓库现有 Docker test image 运行，但必须明确实际
命令，不能写成 `.venv` 通过。不要运行全量 API、Web、系统测试或 OCR。

## 9. 停止条件

遇到以下情况停止并报告，不改产品：

- 某条链无法在不修改产品代码的情况下从真实 orchestration 进入；
- 现有业务合同与 Spec 006 冲突；
- repair 场景只能通过修改 prompt/artifact 实现；
- 正式 Postgres 环境无法建立且只能用 SQLite；
- 测试发现真实产品 bug、调用次数漂移、owner 错绑或敏感信息泄露。

## 10. 交回

更新：

`PART_2_SLICE_2A_DURABLE_PROVIDER_CALL_GLM_HANDBACK.md`

新增“四链 Postgres orchestration”章节，列出：

- 每条链使用的真实入口；
- monkeypatch 的最低层外部边界；
- normal/repair/timeout 的 phase、ordinal、owner、usage 和调用次数；
- 实际命令与逐项结果；
- Postgres 临时库创建和清理确认；
- 产品代码零修改；
- 未 commit、未 push、未运行 OCR。

完成后停止，不进入 Slice 2B。
