# Stage 5 Part 2 Slice 2B GLM 实现任务包

## 1. 任务目标

落实已接受的 Spec 007，为以下高风险路径建立优化前质量基线：

- Java/C++ 编程练习；
- Python 稳定对照；
- scientific Practice 的 Wolfram 调用漏斗；
- Tutor code execution / Wolfram 双 MCP；
- Practice 总题数 `1/3/5/10` 的预算曲线。

本 Slice 只建设样本、eval、受控系统测试、浏览器流程、报告和 Gate，不修复产品质量，
不修改生成/评分/预算合同。

采用一个 Slice、两个批次和一个强制交回点：

1. Batch A：样本合同、分类、报告、三语言与 Wolfram/Tutor 非浏览器受控基线；
2. Batch B：Compose/worker/Playwright/CI 纵向路径。

**首次执行只完成 Batch A，然后停止并交回 Codex。不得提前进入 Batch B。**

真实 provider、Judge0、Wolfram Cloud MCP 由 Codex 在后续人工 Gate 中执行；GLM 不接触
真实 key，不发起远程付费调用。

## 2. 仓库与环境

- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- Shell：PowerShell
- Python：仓库现有 `.venv` / API test image，禁止安装新依赖
- 数据库：正式事实测试使用隔离 Postgres；SQLite 只能用于纯 schema/helper 测试
- Web：`apps/web` 现有 Node/Playwright 依赖
- Docker：复用 `docker-compose.yml`、`compose.system-test.yml`
- 现有受控能力：
  - `tests/system/model_services_stub/server.py`
  - `apps/mcp_execution/adapter.py::FakeExecutionBackend`
  - `apps/mcp_execution/fake_wolfram_server.py`
  - `practice-worker`
  - Stage 4 eval 与三语言 canonical harness tests

不得读取或修改 `.tmp/`、`artifacts/`，不得回滚任何既有 dirty file。开始前运行：

```powershell
git status --short --branch
```

## 3. 必须完整读取

- `AGENTS.md`
- `docs/README.md`
- `docs/LEARNING_AGENT_BLUEPRINT.md`
- `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/README.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/007-high-risk-tool-and-practice-quality-baseline.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/006-controlled-system-tests-and-ci-gates.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/adr/003-controlled-test-boundaries-and-ci-gate-separation.md`
- `docs/04-platform-stage-4-practice-memory-and-review/specs/004-controlled-python-execution-mcp-lab.md`
- `docs/04-platform-stage-4-practice-memory-and-review/specs/005-practice-generation-and-grading-stability.md`
- `docs/04-platform-stage-4-practice-memory-and-review/adr/006-product-owned-mcp-python-execution-boundary.md`
- `docs/04-platform-stage-4-practice-memory-and-review/adr/007-versioned-practice-artifact-validation-and-repair-authority.md`
- 本任务包

若任务包与以上已接受合同冲突，停止对应部分并报告，不得自行改变合同。

## 4. 全局边界

### 4.1 禁止

- 不修改 `apps/api/learn_platform_api/**` 产品代码；
- 不修改 schema、migration、ORM、公开 API、Practice artifact 或 Job 状态；
- 不改变每 Set 最多一个 specialized item；
- 不增加“编程题数量”字段；
- 不提高题数、provider、repair、MCP、step、timeout 或 retry 预算；
- 不修改产品 prompt 以迎合固定样本；
- 不增加关键词识别、固定答案、固定题目或 test-only 产品分支；
- 不把真实 provider/Judge0/Wolfram 放入普通 PR；
- 不记录 prompt、课程原文、题干、答案、代码、tests、compiler/Wolfram 原文、URL、
  key 或绝对路径；
- 不新增依赖；
- 不 commit、不 push、不运行 OCR、不进入 Stage 5 第三部分。

### 4.2 允许

Batch A 允许修改或新增：

- 独立 eval/sample/report 模块；
- API test/eval fixture；
- 非浏览器受控测试；
- 安全聚合基线报告与说明文档；
- 必要的 test-only runner 脚本；
- `.gitignore` 中新测试结果目录的精确忽略项；
- Batch A handback。

首次执行不得修改：

- `.github/workflows/**`
- `compose.system-test.yml`
- `docker-compose.yml`
- `scripts/browser-test.*`
- `apps/web/**`
- `tests/system/**`
- `apps/mcp_execution/**` 产品/test server 实现

若 Batch A 证明必须改上述文件，记录为 Batch B 输入，不提前修改。

## 5. Batch A：固定样本合同

### 5.1 样本不是固定答案

建立机器可读的 allowlisted sample registry。建议放在独立、名称明确的测试目录，例如：

```text
apps/api/tests/quality_baseline/
  samples.py 或 samples.json
  report.py
  test_*.py
```

可以遵循更匹配现有仓库的等价结构，但不得把样本放入产品包。

每个样本只保存：

- `sample_id`
- 能力：`practice_coding | practice_science | tutor_code | tutor_science | negative_control`
- lesson objective/evidence 的脱敏测试 fixture；
- request mode、总题数、单一代码语言；
- `required | optional | forbidden` 工具预期；
- 预期验证的合同分类；
- 不包含真实用户资料或 provider 原始回答。

至少包含：

- 两份真正含可执行目标的算法/编程正例；
- 两份真正含计算/符号/单位目标的科学正例；
- 一个普通概念负对照；
- Tutor code 必要/不必要各一个；
- Tutor Wolfram 必要/不必要各一个。

样本必须证明“题目为什么适合该能力”，不得仅以题名或关键词判断。加入同类措辞变体和
不应触发的反例，防止 eval 自身变成硬编码意图识别。

### 5.2 当前 Practice 题数合同

测试与报告必须明确：

- `item_count` 是 Set 总题数；
- `require_coding` / `require_science` 只要求对应 specialized item 存在；
- v2 每 Set 最多一个 specialized item；
- 总题数大于 1 时，其余是普通题；
- 不得将 `item_count=5` 报告成“5 道编程题”。

## 6. Batch A：安全报告合同

建立纯 eval/report 数据结构，不进入产品 API/ORM。每条运行至少表达：

- sample ID、能力、语言、请求模式、总题数、重复序号；
- controlled/real-remote 层级；
- requested/final item count 和各 item type 计数；
- tool expectation；
- tool requested/authorized/called/succeeded；
- artifact/reference/compiler/grading/final 状态；
- provider phase/status/usage/finish reason；
- repair、provider、MCP 和 step 计数；
- 稳定失败阶段与类别；
- latency、token、已知 CNY cost 或 unknown reason。

科学工具分类至少支持：

- `tool_not_needed`
- `tool_request_missed`
- `authorization_missing`
- `capability_unavailable`
- `schema_drift`
- `mcp_connection_failed`
- `tool_result_invalid`
- `scientific_reference_unverified`
- `artifact_failed_after_tool_success`
- `succeeded_with_wolfram`
- `succeeded_without_wolfram`

分类必须由结构化事实推导，不解析异常正文、日志或自然语言回答。

报告序列化白名单必须有禁止字段测试，至少拒绝：

- prompt/messages；
- lesson/source/evidence 正文；
- stem/answer/rubric；
- source/reference/student code；
- public/hidden tests 与 harness；
- raw provider/compiler/Wolfram input/output；
- key、Authorization；
- URL、绝对路径。

受控基线可生成一个脱敏聚合 snapshot，建议放入当前 Stage 的 `baselines/`；不得提交每次
运行的敏感 raw artifact。若需要临时结果目录，使用新的明确目录并加入精确 `.gitignore`。

## 7. Batch A：三语言编程基线

### 7.1 复用产品入口

测试必须经过现有 Practice generation/grading orchestration 或公开 service 入口，
不得直接把 hand-written source 送给 validator 后声称生成链通过。

允许 monkeypatch：

- 最低层 provider HTTP；
- retrieval；
- execution MCP 的外部 backend/session；
- capability projection。

最终证据必须来自正式 artifact/Job/Attempt/Feedback、AgentRun、ProviderCall、
AgentToolCall 或真实 canonical execution 结果，不以 mock 调用次数作为唯一证据。

### 7.2 矩阵

Python、Java、C++ 各覆盖：

- `item_count=1`
- `require_coding`
- 单一允许语言
- initial success
- specialized repair success
- reference compile failure
- reference test mismatch
- correct submission
- representative wrong submission

Java/C++ 还必须覆盖 canonical wrapper/entrypoint、UTF-8、多行输入输出和编译错误分类。
Python 是对照组，不得用 Python 通过替代 Java/C++。

使用现有 `FakeExecutionBackend` 或既有 compiler fixture 时必须标记
`controlled_backend`；不得报告为真实 Judge0。

## 8. Batch A：总题数预算曲线

为以下矩阵建立参数化受控测试/runner：

- `general_only`：`1/3/5/10`
- `require_coding` + 单一语言：`1/3/5/10`
- `require_science`：`1/3/5/10`

测试输入可以用 scripted provider 构造各题数的合法 artifact、length finish reason、
预算超限和 repair 场景，但必须经过真实业务预算检查与 authority commit。

至少断言：

- 成功时最终题数精确；
- 每 Set specialized item 不超过一个；
- 预算不足使用当前稳定错误，零半成品；
- 高题数没有静默缩减后冒充成功；
- ProviderCall phase/usage/finish reason 与报告一致；
- 失败阶段可归类；
- 不修改当前预算。

这组 controlled matrix 证明计数和分类合同，不冒充真实 provider 在 10 题下的成功率。

## 9. Batch A：Wolfram 调用漏斗

### 9.1 Practice

至少覆盖：

- required 科学样本，模型提出 Wolfram request，授权有效，受控 MCP 成功，Set 发布；
- required 样本未提出 request，分类 `tool_request_missed`；
- requested 但 authorization/readiness/schema/connection/result 各阶段失败；
- Tool 成功但最终 artifact 失败；
- forbidden 简单负对照零 Tool Call；
- grading 本地足够时零调用；
- grading 确实需要远程验证时调用并形成合规结果/失败。

必须复用现有 Wolfram allowlist 与 schema 合同；禁止
`WolframLanguageEvaluator`。

### 9.2 Tutor

至少覆盖：

- code required + authorized -> `run_code`；
- science required + authorized -> `WolframAlpha` 或 `WolframContext`；
- required 但模型未请求 -> request missed；
- authorized negative control -> zero call；
- unauthorized -> zero call；
- capability/schema/connection/result failure -> stable limitation；
- final Turn、AgentRun、ProviderCall、AgentToolCall 对应且预算不超限。

Batch A 可以使用真实 service orchestration + 最低层 fake session/backend，不要求真实浏览器或
RQ 进程。

## 10. Batch A 验收测试真实性

禁止：

- 测试中手工创建期望 AgentRun/ToolCall 再查询；
- 直接调用 recorder/finalizer 作为 orchestration 证据；
- 复制产品分类函数到测试中计算期望；
- `try/except Exception` 后继续断言；
- 裸 `pytest.raises(Exception)` 或不匹配稳定错误；
- Postgres 不可达时 skip；
- 用源码搜索/字符串形状代替行为；
- 固定 sleep 代替状态/服务 readiness。

每项关键证据从新 Session 查询。关键反事实必须证明破坏产品边界会让测试失败。

## 11. Batch A 验证

先运行新增 focused tests，再运行：

```powershell
python -m pytest -q `
  apps/api/tests/test_stage4_eval.py `
  apps/api/tests/test_slice5_practice_stability.py `
  apps/api/tests/test_slice5_practice_worker.py `
  apps/api/tests/test_provider_call_chain_behavior.py
```

若本地 `.venv` 不可用，可使用仓库既有 API test image；必须报告真实命令。

Postgres 测试必须使用随机 throwaway database，不得连接或迁移开发数据库。关键矩阵
不得 skip。

同时运行：

```powershell
git diff --check
```

Batch A 不要求 Web lint/build、Playwright 或 Compose 全栈；因为不允许修改这些范围。

## 12. Batch A 强制 Handback

生成：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2B_BATCH_A_GLM_HANDBACK.md`

必须报告：

- 新增样本及为何工具 required/forbidden；
- 报告 schema 与敏感字段防线；
- 三语言矩阵实际覆盖；
- 题数矩阵与 specialized item 真实语义；
- Practice/Tutor Wolfram 与 code MCP 漏斗覆盖；
- 测试是否经过真实产品入口；
- Postgres 使用方式；
- 每条验证命令和结果；
- 未解决问题与 Batch B 输入；
- 产品代码零修改证明；
- 未 commit、未 push、未 OCR、未进入 Batch B/第三部分。

完成 Batch A 后必须停止，等待 Codex 独立验收。

## 13. Batch B 预告（本轮禁止执行）

只有 Codex 接受 Batch A 后，才会另行下达继续指令。Batch B 将在同一 Spec 007 下：

- 扩展受控 Compose，启动 Practice worker、execution MCP/fake backend、fake Wolfram；
- 建立 Java、C++ 完整 Playwright 生成/作答/评分/运行记录路径；
- 建立 scientific Practice Wolfram required/negative 浏览器路径；
- 建立 Tutor code/Wolfram required/negative 浏览器路径；
- 接入 CI 的 controlled/compiler/browser Gate；
- 输出受控聚合 baseline；
- 由 Codex 完成真实 provider/Judge0/Wolfram 人工 Gate。

Batch B 仍不得修产品质量；发现真实失败只记录第三部分输入。
