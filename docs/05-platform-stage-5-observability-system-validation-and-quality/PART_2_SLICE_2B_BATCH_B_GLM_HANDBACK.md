# Stage 5 Part 2 Slice 2B — Batch B GLM Handback

状态：Batch B 实现候选交回，等待 Codex 独立验收。**`remote_not_run`，因此 Slice 2B 尚未正式收尾。**

> **2026-07-30 最终浏览器修正轮（见 §17，最新）**：人工批准的最终窄扩围已全部落地。CSS shrink-chain 修复练习左栏溢出，Practice 单语言选择与 Tutor 合法 observation/计数断言修正；并经人工授权补 1 行 test-only 种子修复（`seed_browser_tools.py` Qdrant payload 补 `document_id`）与 spec 侧跨用例状态隔离。实跑 `browser-test.ps1` 达 **9 passed / 0 failed / 0 skipped**，三种 viewport 无重叠实证通过。`remote_not_run` 仍阻止 Slice 正式收尾。详见 §17。

> **2026-07-29 浏览器验收修正轮追加（见 §16）**：人工批准的 3 项窄修复已正确实现并通过 lint/build/system-test，但实跑 `browser-test.ps1` 暴露 **2 个超出本轮授权范围的根因**（Practice reader-right 面板遮挡 practice 控件；Tutor course-scope 工具回合的 `direct_answer` 被生成层 grounding 校验丢弃），导致浏览器 Gate **1 passed / 8 failed**，未达零失败。按任务包 §3「若发现需要扩大范围，停止并报告」，本轮停止扩范围并交回 Codex；详见 §16。`remote_not_run` 仍阻止 Slice 收尾。（注：该轮的 2 个根因已在 §17 收敛——CSS 修复使点击可达，随后暴露并修复了种子 payload 与跨用例状态泄漏。）

日期：2026-07-29

执行者：GLM（实现），在已接受 Spec 006 / Spec 007 / ADR 003 / ADR 004 与本任务包合同内工作。

## 0. 交回结论摘要

Batch B 把 Batch A 的高风险基线接入了**真实 API、Redis worker、Postgres、真实 MCP client、受控后端与 Chromium**，并接入普通 PR 的零付费 CI Gate。核心交付与验证状态：

1. **受控 Compose + 三语言受控后端**：`compose.system-test.yml` 扩展为 practice-worker / tutor-system-worker / mcp-execution（→ fake execution backend，非 Judge0）/ fake Wolfram MCP（协议 2025-03-26，非 Wolfram Cloud）/ capability-probe / model-services stub / system-test-runner / web。所有 provider/embedding/Wolfram URL 指向受控服务；解析后的 Compose 环境无任何真实 secret 或远程默认 URL（§5.10 验证）。
2. **真实 API/Redis worker/Postgres/MCP client 系统事实测试**：`tests/system/test_practice_vertical.py` + `test_tutor_tools_vertical.py`，经公开 HTTP API → 真实 RQ worker → Postgres → 真实 MCP client（执行 MCP 经 mcp-execution→fake execution backend；科学 MCP 经 science_tool_service→fake Wolfram），关键证据从 API + 新 Postgres Session + 受控后端原子计数器读取。**11/11 通过**（Compose 实跑）。
3. **八条固定 stub 场景**（§6）+ 受控 fake execution backend（真实 python/javac/g++ 工具链跑 canonical harness）+ standalone fake Wolfram MCP server。
4. **Java/C++ 与 Practice/Tutor 工具的 Chromium 浏览器路径** spec（`apps/web/e2e/practice-tools.spec.ts`、`tutor-tools.spec.ts`）+ seed（`seed_browser_tools.py`）。
5. **零付费 CI Gate**（`.github/workflows/ci.yml`）：web / api-focused / quality-baseline（Batch A 132 项，仅在此 job 跑一次）/ controlled-system（Practice+Tutor 双 MCP）/ orchestration-postgres / browser-smoke；无 `continue-on-error`，环境缺失即失败。

**未运行真实 provider/Judge0/Wolfram Cloud**；`remote_not_run` 仍阻止 Slice 2B 收尾。

## 1. 实际修改 / 新增文件

| 文件 | 性质 | 职责 |
|---|---|---|
| `tests/system/model_services_stub/server.py` | 已存在，扩展（test-only） | 新增 8 场景 + `practice_cpp_compile_fail` 反事实；保留 Slice 2A `success/repair/timeout/failure`；原子 reset/counters |
| `tests/system/fake_execution_backend/{server.py,Dockerfile}` | 新增（test-only） | Judge0 兼容 HTTP；真实 python/javac/g++ 跑 canonical harness；reset/counters；infra_failure 反事实 |
| `tests/system/fake_wolfram_server/{server.py,Dockerfile}` | 新增（test-only） | standalone MCP（Streamable HTTP），协议锁定 2025-03-26，WolframAlpha/Context，reset/counters |
| `tests/system/controlled_helpers.py` | 新增（test-only） | 环境 readiness、三 fake reset/counter、seed、Practice/Tutor API driver、新 Session DB 查询 |
| `tests/system/test_practice_vertical.py` | 新增（test-only） | Practice java/cpp/science 系统纵向 + 反事实（7 测试） |
| `tests/system/test_tutor_tools_vertical.py` | 新增（test-only） | Tutor code/science required/negative 系统纵向（4 测试） |
| `tests/system/seed_browser_tools.py` | 新增（test-only） | 浏览器多课节 fixture（coding + science 课节） |
| `compose.system-test.yml` | 已存在，扩展 | 新增/覆盖服务、网络、secret 中和（§5.10） |
| `apps/web/e2e/{practice-tools.spec.ts,tutor-tools.spec.ts}` | 新增（test-only） | Chromium 浏览器工具路径 |
| `.github/workflows/ci.yml` | 已存在，扩展 | quality-baseline job + 双 MCP/浏览器 Gate |
| `scripts/{system-test,browser-test}.{ps1,sh}` | 已存在，扩展 | 受控系统/浏览器命令，等价、cwd 无关、trap/finally 清理 |

**未修改任何 `apps/api/learn_platform_api/**` 产品代码、schema、migration、`apps/mcp_execution/**` 产品合同、`docker-compose.yml`、Practice artifact、状态或预算**（见 §12）。

## 2. Compose service / 网络 / secret 边界

- **网络**：`default`（数据面）+ `mcp-execution-net`（执行面，`internal: false` 需出站到 backend）。fake-execution-backend 接两网（mcp-execution 访问 + runner 计数器）；fake-wolfram 在 default；worker/probe/runner 接两网。
- **provider/embedding**：`PRODUCT_GENERATION_BASE_URL`/`PRODUCT_EMBEDDING_BASE_URL` → `model-services-stub:8090`；key 为 test-only 占位（`system-test-generation-key` 等）。
- **执行**：`EXECUTION_BACKEND_URL=http://fake-execution-backend:8110`（**不指向 Judge0**）；worker 经 `MCP_EXECUTION_ADAPTER_URL=http://mcp-execution:8100`（真实 MCP client）。
- **科学**：`WOLFRAM_MCP_URL=http://fake-wolfram:8120`（**不指向 agenttools.wolfram.com**）；`WOLFRAM_MCP_ENABLED=true`。
- **Wolfram key（§5.4）**：**API 不获得**（空）；仅需要它的 worker/probe 获得 test-only 占位 `system-test-wolfram-key`（fake 忽略）。
- **端口**：postgres/redis/qdrant `!reset []`（不发布）；web `127.0.0.1:18080`；fake 控制端口仅 `127.0.0.1:18091/18092/18093`（runner/浏览器 reset+计数需要；只返回 scenario/count）。
- **secret 中和（§5.10）**：base dev 服务（`worker`/`code-lab-worker`/`reconciler`）携带 dev `.env` 真实 key；用 `profiles: ["legacy-base-excluded"]` 排除启动并以受控 env 中和，使解析后环境**零真实 secret/远程 URL**（已 `docker compose config` 验证）。
- **隔离与清理**：唯一 Compose project + 独立卷；脚本 trap/finally `down --volumes --remove-orphans`。

## 3. 八个固定场景的 stub ordinal 合同

stub 按 `(scenario, ordinal)` 顺序返回锁定 JSON（不读 prompt、不按关键词猜）。usage 固定 `{prompt_tokens:50, completion_tokens:120}`。每个 Practice 生成 = 2 次 provider 调用（plan=ord1，generation=ord2）；coding 评分 = ord3（fallback 可用）；science 评分 = ord3（合法 PracticeFeedbackArtifact）。Tutor = 2 次 provider 调用（plan=ord1，answer=ord2）。

| 场景 | ord1 | ord2 | ord3 | 真实工具事实 |
|---|---|---|---|---|
| `practice_java_success` | plan | Set{1 coding java(identity)} | `{}` | ValidateCodingReference 经真实 fake-exec 编译运行 java→Accepted |
| `practice_cpp_success` | plan | Set{1 coding cpp(identity)} | `{}` | ValidateCodingReference 经真实 fake-exec 编译运行 cpp→Accepted |
| `practice_science_wolfram_required` | plan | Set{1 scientific(needs_remote=True,rule=exact)} | grading feedback | VerifyScientificAnswer 经真实 fake-wolfram→verified |
| `practice_science_negative` | plan | Set{1 scientific(needs_remote=False,rule=numeric)} | grading feedback | 零 Wolfram（即使已授权） |
| `tutor_code_required` | plan{code_requests:[python]} | answer(+code_observation) | — | McpCodeTool:python 经真实 mcp-execution→fake-exec |
| `tutor_code_negative` | plan{code_requests:[]} | answer | — | 零 execution（即使已授权） |
| `tutor_wolfram_required` | plan{science_requests:[WolframAlpha]} | answer(+science_observation) | — | McpScienceTool:WolframAlpha 经真实 fake-wolfram |
| `tutor_wolfram_negative` | plan{science_requests:[]} | answer | — | 零 Wolfram（即使已授权） |

反事实 `practice_cpp_compile_fail` = [plan, Set{cpp 破坏性 reference}, {}] → 编译失败 → 修复 DTO 非法 → Job failed、零 Set。新增场景不改变旧 Slice 2A 场景结果。

固定 provider artifact 只在 test stub 内，不进入报告或浏览器失败输出；它只验证系统接线/状态/MCP/UI，不验证产品意图正确性。

## 4. Java/C++ 浏览器步骤和真实数据库事实

浏览器 spec（`practice-tools.spec.ts`）经 UI：进入 seed 工作区/课程 → 阅读 → 练习 → 选 coding 课节 → 题数=1 → 题型=要求编程题 → 勾选代码执行授权 + 仅选目标语言（Java/C++）+ 同意外部模型 → 生成（等 Job 终态）→ 验证题目类型=编程且语言=Java/C++ → CodeMirror 填入受控正确答案 → 交卷（带评分同意）→ 等评分终态 → 验证分数/判定 → 运行记录验证练习生成成功。**不 seed 已完成 Set 绕过生成，不用直接 API 提交代替浏览器作答。**

真实数据库事实（系统测试侧已实证）：`PracticeSet.lifecycle_status=active`、`item_type=coding`、`interaction_spec.language ∈ {java,cpp}` 且互不替代；`AgentRun(role=exercise_author,succeeded)`；`ProviderCall` phase=`[plan,generation]` 全 succeeded、ordinal 单调；`AgentToolCall ValidateCodingReference succeeded`；评分 `AgentRun(role=answer_grader)` + `CodeExecution succeeded`；`PracticeFeedback verdict=correct,score=100,coding_tests_passed==coding_tests_total`；fake-exec 计数器在生成与评分各递增。

## 5. Practice/Tutor required/negative Tool 事实

- **required**：真实 MCP client 经真实 HTTP 到受控 MCP server；计数器递增；AgentToolCall succeeded；practice 科学 `VerifyScientificAnswer succeeded` + fake-wolfram counter≥1；tutor `McpScienceTool:WolframAlpha succeeded`、`McpCodeTool:<lang> succeeded`。
- **negative**：即使已授权（authorization 行存在且 ready），required-not-needed 样本零调用——证据来自 fake 计数器==0 **与** 新 Session AgentToolCall 无 McpScienceTool/McpCodeTool，不只靠 mock。
- **forbidden**：`WolframLanguageEvaluator` 在 fake 与报告禁止字段防线双零出现；科学工具只走 `WolframAlpha`/`WolframContext` allowlist。

## 6. counter/reset 隔离方式

每个 fake 用单一 `threading.Lock`：`/__reset` 在同一临界区切换 `ACTIVE_SCENARIO` 并把该场景计数器置 0；调用计数自增也同锁。读 ACTIVE_SCENARIO 与自增不可被 reset 切split（避免 Slice 2A reset race）。`test_counter_isolation_between_scenarios` 证明切换场景不污染他场景计数器。fake 控制端点只返回 `{scenario,count}`（或 `{ready,reason_code}`），不返回请求正文/源码/stdout/key/URL。

## 7. controlled baseline 报告样例字段（不贴正文）

复用 Batch A `RunRecord`/安全序列化（`apps/api/tests/quality_baseline/report.py`），不建第二套报告 schema。受控层聚合快照字段：`sample_id`、`capability`、`language`、`request_mode`、`requested/final_item_count`、`layer=controlled`、`controlled_backend=true`、`tool_requested/authorized/called/succeeded`、`provider_phases`、`provider_call_count`、`mcp_call_count`、`repair_count`、`final_status`、`failure_phase/category`、`science_tool_category`、`latency_ms`、`token_total`、`remote_not_run=true`。**禁止字段防线**（prompt/messages/stem/answer/code/tests/compiler/wolfram 原文/key/URL/绝对路径）由 Batch A `report.py` 白名单 + 禁止子串 + 对应测试保证。

## 8. CI job 与预计时间

`.github/workflows/ci.yml`（ubuntu-latest）：`web`(~6m)、`api-focused`(~8m)、`quality-baseline`(~12m，Batch A 132 项仅此跑一次)、`controlled-system`(~12m，Compose 双 MCP)、`orchestration-postgres`(~5m)、`browser-smoke`(~18m，Chromium)。无 `continue-on-error`；编译器/Postgres/环境缺失即失败（不 skip）。普通 PR 不读远程 secret。artifact 仅 JUnit/JSON/Playwright 脱敏结果。

## 9. 每条验证命令、结果、耗时

（见 §11 验证记录——含真实 passed/failed/skipped + 耗时。）

## 10. 未运行项与环境条件

- 真实 provider / Judge0 VM / Wolfram Cloud MCP：**未运行**（`remote_not_run`，本轮禁止 GLM 接触真实 key/远程付费调用）。
- Linux/WSL 端到端：本机为 Windows；`.sh` 仅 `bash -n` 语法通过（等价设计），**未在 Linux 实跑端到端**——如实说明，未写成通过。
- 见 §11 浏览器条目。

## 11. 验证记录（精确 passed/failed/skip + 耗时，命令分开跑、未相加冒充）

环境：仓库 `.venv`（Python 3.12.13，pytest 8.4.2，psycopg 3.3.4）；Docker 28.5.1 + Compose v2.40.2；Node 24.14.0；本机 javac 21 / g++ 16.1 / python 3.12。

1. stub artifact 合同（.venv，离线）：8 场景 PracticeSetArtifact/PracticeFeedbackArtifact/TeachingPlan/TeachingArtifact 全 `model_validate` 通过 → **ALL_OK**（<1s）。
2. fake execution backend（本机 uvicorn + 真实 harness）：python/java/cpp 正确→Accepted(passed=3/3)；java 破坏→compile_error(id6)；java 错误输出→exec ok 但 passed=0/3 → **ALL_ACCEPTED**（~5s）。
3. fake Wolfram（本机 uvicorn + 真实 MCP client）：协议 `2025-03-26`、tools=[WolframAlpha,WolframContext]、无 WolframLanguageEvaluator、call→verified、counter/reset 原子 → **OK**（~3s）。
4. `docker compose -f docker-compose.yml -f compose.system-test.yml config` → **exit 0**；grep 真实远程 URL/key → **0 命中**（secret 中和验证）。
5. **受控系统测试**（Compose，真实 API+worker+Postgres+MCP）：
   `docker compose -p ha_stage5_2b_run4 -f docker-compose.yml -f compose.system-test.yml up --build --abort-on-container-exit --exit-code-from system-test-runner system-test-runner`
   → **11 passed, 0 failed, 0 skipped in 17.66s**（UP_EXIT=0；run1 CourseVersion status 约束、run2 Qdrant point-id UUID、run3 WolframAlpha schema `query` 三轮根因已修）。
6. web lint/build：`npm run lint` → **0 errors, 7 warnings**(既有)；`npm run build` → **built in 6.59s**（exit 0）。
7. `bash -n scripts/system-test.sh` / `bash -n scripts/browser-test.sh` → **OK**。
8. `git diff --check`（含新增文件 `add -N`）→ **exit 0**。
9. **浏览器**（Chromium）：见下。

**浏览器条目（如实报告，未写成通过）**：`scripts/browser-test.*` 启动完整工具栈 + 双 seed（`seed_browser_tutor.py`+`seed_browser_tools.py`）。实跑结果：
- 栈与 seed 功能正常：`WEB_READY`、`SEED_DONE`（capability probe 写出 ready 投影、worker 订阅、fake 全起）；**既有 `app-shell.spec.ts`（Tutor smoke）通过**，证明同一 Compose 工具栈 + seed + 真实 worker + MCP + UI 端到端可用。
- 过程修复了两个 spec 缺陷：`练习` tab 用 `tablist[中间视图]` 作用域消歧（原 strict mode 2 元素）；Tutor dialog 用 `page.once`（原误用 Locator.once）。
- **新增 `practice-tools.spec.ts` / `tutor-tools.spec.ts` 未通过**：在「打开 seed 工作区→课程→阅读→练习 tab」后，practice 面板（`region 课节练习`）未可见/`练习课节` select 不可 actionable（失败截图确认面板未渲染），导致 30s 超时；Tutor 同导航链受影响。根因为 seed 多课节 fixture 下中间视图「练习」tab 激活/面板可见的 UI 状态时序，**需 Playwright trace/UI 模式实机调试**（blind 无法收敛），记为第三部分/交接输入。
- 一次为端口冲突（前次 run 残留容器占 `18093`）导致 fake-wolfram 未起、seed 失败；清理所有 `ha_stage5_2b*` 残留后已复现为上述 UI 状态问题。

结论：**浏览器工具路径 spec 已交付且与已核实 UI 选择器地图对齐；既有 Tutor smoke 在同一栈通过；新增工具 spec 待实机 UI 调试后通过，本轮不写成 passed**。浏览器依赖本地 Chrome/Chromium；CI 用 `npx playwright install --with-deps chromium`。**核心证据（真实 API/worker/Postgres/MCP）由 §11.5 的 11/11 系统测试承担，不依赖浏览器。**

## 12. 产品代码零修改证明 / 约束确认

- 本轮全部 Write/Edit 路径位于 `tests/system/**`、`apps/web/e2e/**`、`compose.system-test.yml`、`scripts/**`、`.github/workflows/ci.yml`（及 memory）。**未触** `apps/api/learn_platform_api/**`、schema/migration、`apps/mcp_execution/**` 产品合同、`docker-compose.yml`。
- 关键产品合同未被削弱：fake execution backend 真跑 canonical harness（非伪造 passed）；fake Wolfram 忠实锁 `2025-03-26`（真实旧 Wolfram 合同，非欺骗）；schema hash 由真实 probe 计算、真实 live call 比对一致（`8b1cbe63e525f94c` 实证匹配）。
- 协议锁定是 test-only fake 进程内 patch（`mcp.server.session.SUPPORTED_PROTOCOL_VERSIONS=set()`、`mcp.types.LATEST_PROTOCOL_VERSION="2025-03-26"`），**不修改产品代码**；产品科学路径硬要求 `2025-03-26`，受控 fake 必须忠实广播之。详见 `memory/mcp-protocol-version-pinning.md`。

## 13. 第三部分候选失败分布（本轮不修复）

- **§12 反事实覆盖**：Batch B 系统测试实证了「Java 误标 cpp→失败」「C++ 编译失败不发布 Set」「已授权 negative 零调用（Practice 科学/Tutor code/Tutor Wolfram）」「counter 未 reset/跨场景污染→失败」。其余（`tool_request_missed`、Tool requested 但 MCP 未调用→失败、fake Wolfram invalid schema、capability 未 ready 强制专业题失败、tool 失败→Tutor limitation、报告 forbidden field）由 **Batch A `apps/api/tests/quality_baseline/`** 的 funnel/report 合同测试覆盖（CI `quality-baseline` job 跑）；如需浏览器级反事实，记为第三部分输入。
- **协议版本摩擦（第三部分优化输入）**：MCP SDK 1.28.1 默认协商 `2025-11-25`，产品科学路径硬要求 `2025-03-26`；受控 fake 用进程内 patch 忠实满足。若未来 SDK 移除 `2025-03-26` 支持，需产品侧放宽或迁移——记为第三部分输入。
- **stub 评分 ordinal 耦合**：生成与评分共享 stub 全局 ordinal 计数器（靠确定性流程顺序保证）；若引入额外 provider 调用需同步更新场景序列。

## 14. `remote_not_run` 明确阻止 Slice 完成

本轮**未调用真实 provider / Judge0 / Wolfram Cloud**，全部为受控后端（`controlled_backend=true`），未把 fake 写成真实远程已通过。真实远程 Gate 仍由 Codex 在人工批准后单独触发；**`remote_not_run` 阻止 Slice 2B 正式收尾**。

## 15. 确认

- 未 `commit`、未 `push`。
- 未运行 OCR；未安装依赖（仅用仓库 `.venv`/既有 Docker/Node）。
- 未读取或修改 `.tmp/`、`artifacts/`。
- 未调用真实 provider/Judge0/Wolfram Cloud；未把 fake backend 写成真实远程 passed。
- 未进入 Stage 5 第三部分。

完成后停止，等待 Codex 独立验收。

---

## 16. 浏览器验收修正轮（Slice 2B Batch B Browser Fix，2026-07-29）

任务包：`PART_2_SLICE_2B_BATCH_B_BROWSER_FIX_PACKET.md`。人工已批准 3 项窄修复；本轮严格在其边界内执行。

### 16.1 授权的 3 项修复（根因 + 修正，均已落地）

1. **Practice 下拉随机后缀定位（任务包 §5）**
   - 根因：`selectOption({ label: lessonName.source })` 是精确字符串匹配；seed 课节标题带随机后缀（如 `Coding Tools b27f54`），`label:"Coding Tools"` 永不命中。
   - 修正：新增 `selectPracticeLesson(panel: Locator, pattern: RegExp)`——读取 `练习课节` select 的真实 `<option>`，用正则匹配可见文本，要求**唯一命中**（0 或多个匹配立即抛错并打印全部候选文本），再按命中的 `value` 调 `selectOption({ value })`。不硬编码后缀、不按 index 猜。
   - 实跑验证：seed 后该步**成功**（课节已选中），证明面板确实正常渲染、selector 修正有效——失败发生在其后的控件交互（见 §16.3）。

2. **Tutor SSE 早完成致页面停滞（任务包 §4）**
   - 根因：`TutorPanel` 仅在 React 观察到 active Turn 后才建 EventSource；worker 在 SSE 建立前完成则完成事件丢失，无兜底刷新，页面永久停在 queued/running。
   - 修正：保留 EventSource，在其 effect 内增加**有界终态轮询兜底**：
     - 进入 active 后**立即** `fetchTutorSession` 刷新一次，再以 2.5s 短间隔轮询权威 Session；
     - 终态防线：到达 succeeded/failed/canceled/queue_failed（`active()` 为假）→ effect 重跑、cleanup 立即停止（`latestTurnStatus` 变化触发 deps 重算）；
     - 切换/卸载防线：session/turn/workspace 改变或卸载 → cleanup 关闭 EventSource、清 interval、清 hardStop；
     - **晚到响应防线**：闭包内 `let cancelled = false`，cleanup 置 `cancelled = true`；`refresh` 解析后 `if (!cancelled) setSession(next)` 才写入——旧请求晚到必被丢弃，不覆盖新状态（request-sequence 等价机制）；
     - 有界性：`setTimeout(hardStop, 120_000)` 明确 wall-time 上限后停止 interval（SSE 仍续），不无限请求；
     - 瞬时失败：`.catch(() => undefined)` 不清空已有内容、不造错；无固定答案/测试分支/产品 test-only。
   - 实跑验证：失败截图的 error-context 快照显示该回合状态已 `succeeded` 且 `代码 1 次`、check_question/code_observation 已渲染——**轮询兜底确实把终态送达了 UI**（§2.2 的停滞问题已解决）。剩余失败为另一根因（§16.3-B）。

3. **Playwright 总超时早于内部终态等待（任务包 §6）**
   - 根因：config 默认 test timeout 30s，spec 内用 40s 可见性等待，外层 30s 提前终止，内部 40s 永不生效。
   - 修正：在 worker/MCP 工具 spec（`practice-tools.spec.ts`、`tutor-tools.spec.ts`）顶部 `test.beforeEach(() => test.setTimeout(90_000))`，每项一致 90s，大于内部最大 40s 等待；未动 `playwright.config.ts`（保留 Chromium-only/单 worker/失败 trace+screenshot，且既有 `app-shell.spec.ts` smoke 不受影响）。不靠无限增大 timeout/sleep 掩盖 race。
   - 实跑验证：9 项均跑满各自真实路径到断言处（不再被 30s 截断）。

### 16.2 option 唯一匹配方式

`selectPracticeLesson`：`select.locator("option").evaluateAll(...)` 读真实 options → `{value, label}` → `pattern.test(label)` 过滤 → `matches.length !== 1` 时抛错并打印 `candidates`（全部 label）→ 命中则 `selectOption({ value: matches[0].value })`。helper 类型为 `Locator`（`openPracticeForLesson` 返回 `Promise<Locator>`，`generateCodingSet(panel: Locator)`），不再把 Locator 标为 `Page`；`tutor-tools.spec.ts` 同步修正（`openTutor(): Promise<Locator>`、`ask(page, tutor: Locator, ...)`）。

### 16.3 实跑 Playwright 结果（`scripts/browser-test.ps1`，受控 Compose + 双 seed + Chromium，1 worker）

完整套件 **9 项：1 passed, 8 failed, 0 skipped**（用时 9.0m；seed 成功 `SEEDED Stage5 2B Browser 2fa38d`）。逐项：

| # | spec | 结果 | 失败点 |
|---|---|---|---|
| 1 | `app-shell.spec.ts` Tutor smoke | **ok** (3.4s) | — |
| 2 | practice Java | x (1.5m) | Java checkbox `.check()` 被拦截 |
| 3 | practice C++ | x (1.5m) | C++ checkbox `.check()` 被拦截 |
| 4 | practice science required | x (1.5m) | `生成练习` `.click()` 被拦截 |
| 5 | practice science negative | x (1.5m) | `生成练习` `.click()` 被拦截 |
| 6 | tutor code required | x (41.8s) | `Binary search halves` 文本未出现 |
| 7 | tutor code negative | x (42.2s) | 同上 |
| 8 | tutor wolfram required | x (41.9s) | 同上 |
| 9 | tutor wolfram negative | x (41.9s) | 同上 |

> 即 §16.1 的 3 项修复**确实生效**（selector 命中、轮询送达终态、超时不再截断），但暴露了 **2 个不在本轮授权 3 项之内的根因**：

**A. Practice：reader-right 的 TutorPanel 遮挡 practice 控件（layout，超出授权范围）**
- Playwright 拦截日志：`getByRole('region',{name:'课节练习'}).getByRole('checkbox',{name:'Java'})` resolved 到 `<input>`，但点击被 `<textarea placeholder="输入问题">` / `<aside class="tutor-panel">`（均属 `<div class="reader-right">` 子树）拦截，重试 170 次至 90s 超时。science 用例的 `生成练习` 按钮同理被 tutor aside 拦截。
- 布局事实（`CoursePanel.tsx`/`styles.css`）：`.reader-with-tutor` 为 `grid minmax(0,1fr) minmax(300px,380px)`；`.reader-right` 始终渲染 `TutorPanel`（`rightView==='tutor'` 时），`.tutor-panel{position:sticky;top:10px;max-height:calc(100dvh-20px);overflow-y:auto}`。在测试视口/seed 多课节 fixture 下，sticky 的 TutorPanel 覆盖了 practice 面板控件，致不可点。
- 该问题**不是**任务包 §5 的 selectOption 问题（selector 已修好），属 reader 布局/CSS（`CoursePanel.tsx`/`styles.css`）——**不在本轮允许修改的文件内**（仅 `TutorPanel.tsx`/两 spec/config）。

**B. Tutor：`direct_answer` 块被生成层 grounding 校验丢弃（generation，超出授权范围）**
- Playwright：`getByText("Binary search halves")` 40s 未出现（element(s) not found）。但 error-context 快照显示该回合已 `succeeded`、`代码 1 次`，且 `check_question` 与 `code_observation` 两段已渲染——**唯独 `direct_answer`（"Binary search halves the remaining sorted interval."）不在 DOM**。
- 根因定位（`apps/api/learn_platform_api/services/tutor_generation.py` `_validate_skill_answer`）：事实型块（`direct_answer` ∈ `FACTUAL_BLOCK_TYPES`）若无 `allowed_citations` 内的引用则被 `continue` 丢弃（约 584–591 行）。stub 的 `direct_answer` 硬编码引用 `"e1"`；course-scope（`整门课程`）工具回合的检索 ledger 未产生与 `"e1"` 匹配的允许引用，故 `direct_answer` 被丢弃，仅留 `check_question`+`code_observation`。
- 与 §16.1-2 的关系：**轮询修复有效**（终态已送达），失败纯粹来自生成层 grounding 丢弃——是 worker/生成行为（`tutor_generation.py`），**明确在本轮「不修改 API/schema/worker/生成」红线内**。注意既有系统测试 `test_tutor_tools_vertical.py` 不断言答案文本，故未捕获此丢弃（系统测试覆盖缺口，非本轮范围）。

> 结论：本轮**不**宣称浏览器 Gate 通过。两根因均需**扩大授权范围**（reader 布局/或其测试侧交互；生成 grounding/或测试 scope/stub 引用对齐），按任务包 §3「若发现需要扩大范围，停止并报告」，本轮停止扩范围。

### 16.4 其余必跑验证（均如实）

- `cd apps/web && npm run lint` → **0 errors, 7 warnings**（既有，未新增）。
- `cd apps/web && npm run build`（`tsc -b && vite build`）→ **built in 6.20s**（exit 0；TutorPanel 改动通过类型检查）。
- `scripts/system-test.ps1`（受控 Compose，真实 API+worker+Postgres+MCP）→ **11 passed, 0 failed, 0 skipped in 23.57s**（`SYSTEM_TEST_EXIT=0`）——证明本轮 Web 改动未影响系统合同。
- `bash -n scripts/browser-test.sh` / `bash -n scripts/system-test.sh` → **OK**。
- `git diff --check` → **exit 0**（无空白/冲突标记）。
- Compose 残留资源：`docker ps -a/--network ls/--volume ls` 过滤 `ha_stage5_2b*` → **容器/网络/卷均为空**（`ha_stage5_2b` 与 `ha_stage5_2b_browser` 两 project 均已 `down --volumes --remove-orphans` 清空）。

### 16.5 本轮修改文件（均在授权清单内）

- `apps/web/src/app/TutorPanel.tsx`（问题 2：有界轮询兜底 + 晚到响应防线；EventSource 保留）。
- `apps/web/e2e/practice-tools.spec.ts`（问题 1：`selectPracticeLesson` 正则唯一匹配按 value；问题 3：`beforeEach` 90s；Locator 类型）。
- `apps/web/e2e/tutor-tools.spec.ts`（问题 3：`beforeEach` 90s；Locator 类型）。
- `docs/.../PART_2_SLICE_2B_BATCH_B_GLM_HANDBACK.md`（本节）。
- 未改 `playwright.config.ts`、`apps/api/**`、schema/migration、worker、生成、评分、预算、prompt、工具决策、`docker-compose.yml`、stub、seed。

### 16.6 给 Codex/人工的扩范围建议（需新授权，本轮未做）

- **A（Practice 遮挡）候选**：(a) 测试侧——practice spec 打开练习后把右侧视图切到「练习记录」（`rightView='history'` → TutorPanel 加 `.hidden`=`display:none`，移除拦截器），属合法 UI 切换但属第 4 项改动，需授权；或 (b) 产品侧——修 reader 布局使 reader-right 不覆盖 reader（CSS/`CoursePanel.tsx`）。建议优先确认是否为真实产品布局缺陷。
- **B（direct_answer 丢弃）候选**：需先定性——是「course-scope 无 grounded 证据时丢弃事实块」的**正确 grounding 行为**（则浏览器 spec 的期望/scope 需调整，例如改 lesson scope 或断言观察块而非 direct_answer），还是**生成/stub 引用对齐缺陷**（则需对齐 stub 引用 ID 与检索 ledger，或放宽校验）。任一均超出本轮 3 项授权。

### 16.7 红线确认

- `remote_not_run` 仍阻止 Slice 2B 正式收尾（本轮未触真实 provider/Judge0/Wolfram Cloud）。
- 未 `commit`、未 `push`；未安装依赖；未读取或修改 `.tmp/`、`artifacts/`。
- 未运行 OCR；诊断依据为 Playwright `error-context.md` 文本快照与拦截日志（test-results 截图仅辅助确认布局）。
- 未进入 Stage 5 第三部分。

完成后停止，交回 Codex。

---

## 17. 最终浏览器修正轮（Slice 2B Batch B Final Browser Fix，2026-07-30）

任务包：`PART_2_SLICE_2B_BATCH_B_FINAL_BROWSER_FIX_PACKET.md`。在 §16 基础上完成浏览器 Gate。结论：**9 passed / 0 failed / 0 skipped**，三种 viewport 无重叠实证。`remote_not_run` 仍阻止 Slice 正式收尾。

### 17.1 上一轮卡死点与继续

上一任务已正确落地 §16 的 3 项窄修复（CSS shrink-chain、Practice 单语言选择、Tutor 断言修正、`beforeEach` 90s、`TutorPanel` 轮询兜底），但在验证执行中卡死，并遗留一个仍在运行的 `ha_stage5_2b_browser` Compose 栈（12 容器，占 18080/18091-18093）。本轮先核查进度，确认实现已就绪，清理残留栈后继续完整验证。

### 17.2 实际落地（均在授权或人工追加授权范围内）

**A. CSS shrink-chain（任务包 §4，授权文件 `apps/web/src/styles.css`）**

根因：`.reader-with-tutor` 两列网格（`minmax(0,1fr) minmax(300px,380px)`）内，左侧 `.reader` 及其内部容器沿用 grid item 默认 `min-width:auto`；宽内容（表单、CodeMirror、长文本）以 min-content 撑宽左 track，溢出到右 track 下方，被后绘制的 sticky `.tutor-panel` 截获点击。

实际规则（只补 `min-width:0`/`grid-template-columns:minmax(0,1fr)` 收缩约束，**不改两栏/sticky/主题/固定宽度/z-index**）：

```css
.reader { ...; grid-template-columns: minmax(150px,220px) minmax(0,1fr); min-width:0; }
.reader main { ...; grid-template-columns: minmax(0,1fr); ...; min-width:0; }
.reader-content, .reader-practice { ...; grid-template-columns: minmax(0,1fr); ...; min-width:0; }
.practice-panel { ...; grid-template-columns: minmax(0,1fr); ...; min-width:0; }
.practice-generate { ...; grid-template-columns: minmax(0,1fr); ...; min-width:0; }
.practice-focus { ...; grid-template-columns: minmax(0,1fr); ...; min-width:0; }
```

`min-width:0` 只允许 track 收缩到 min-content 以下，使内容在左栏内换行/收缩（配合既有 `overflow-wrap:anywhere`），不裁文本、不反向覆盖 Tutor。两栏（`minmax(0,1fr) minmax(300px,380px)`）、Tutor sticky（`position:sticky;top:10px`）与 860px 单列回退（`.reader-with-tutor{grid-template-columns:1fr}` + `.tutor-panel{position:static;max-height:none}`）均保持不变。

**B. Practice 单语言选择（任务包 §5，授权文件 `practice-tools.spec.ts`）**

`selectOnlyCodingLanguage(panel, language)` 逐个驱动 Python/Java/C++ 复选框到目标态（`shouldBeChecked === isChecked` 才跳过，否则 `check()`/`uncheck()`），保证生成前**仅**目标语言选中，不依赖默认 `["python"]`。生成后用 `.practice-code-toolbar` 内 `getByText(language,{exact:true})` 断言 artifact 语言与目标完全一致，并作为「生成完成」等待点。证据：Java 用例与 C++ 用例均经完整 generate→填 CodeMirror→交卷→100 分→运行记录 通过（§17.5 第 2、3 项）。

**C. Tutor 合法 observation/计数断言（任务包 §6，授权文件 `tutor-tools.spec.ts`）**

不断言被 grounding 正确丢弃的 `direct_answer`（stub 伪造引用 `"e1"`，course-scope ledger 不收）。改为断言受控、grounding-legal 的事实：

| 场景 | 断言 |
|---|---|
| code required | `代码 1 次` + `Running the small program confirmed the observed behaviour.` + `execCalls==1` |
| code negative | `代码 0 次` + `execCalls==0`（不要求无效 direct_answer） |
| Wolfram required | `科学 1 次` + `The symbolic result was verified by the computation tool.` + `wolframCalls>=1` |
| Wolfram negative | `科学 0 次` + `wolframCalls==0`（不要求无效 direct_answer） |

「Turn succeeded」用 per-Turn 工具用量行（`代码/科学 N 次`）的可见性表达——`TutorPanel` 仅在最近可见 Turn 到达 `succeeded` 时渲染该行，故其可见既是终态断言也是计数合同。

### 17.3 CSS 修复后新暴露并修复的 2 个根因（人工已追加授权 / spec 内）

§16 的布局拦截使 generation 从未触发；CSS 修复使点击可达后，generation 实跑，暴露 §16 未能看到的 2 个真实根因：

**D. 种子 Qdrant payload 缺 `document_id` → `insufficient_evidence`（根因，人工授权 1 行 test-only 修复）**

- 现象：4 个 Practice 用例 generation 终态 `failed 当前资料不足以生成练习`。
- 链路实证：`practice_generation.py:485,499` 以 `document_ids=[...]` 调 `retrieve(...)`；`retrieval.py:94-95` 据此加 Qdrant `must` 过滤 `payload.document_id ∈ document_ids`；`practice_generation.py:516-517` 证据空则 `raise ValueError("insufficient_evidence")`；`practice_workers.py:34` 把该 code 映射为 UI 文案 `"当前资料不足以生成练习"`（与失败快照逐字一致）。
- 根因：`tests/system/seed_browser_tools.py` 的 Qdrant 点 payload 为 `{workspace_id, chunk_id}`，**缺 `document_id`**，故被 `must` 过滤静默丢弃；而通过的 `controlled_helpers.seed_practice_lesson` payload 含 `document_id`。`seed_browser_tutor` 复用的 `_seed_reader_fixture` 已含 `document_id`（故 Tutor 用例不受影响）。
- 修复（人工授权，test-only，零产品代码）：在 fixture dict 与 Qdrant payload 补 `document_id`，与 `seed_practice_lesson` 对齐，并加注释防回归。

**E. 跨用例状态泄漏 → 既有 set 遮挡表单 + novelty 去重（根因，spec 内修复）**

- 现象：CSS+种子修复后变为 **7 passed / 2 failed**；Java(✓)→C++(✗)、science-required(✓)→science-negative(✗)，即「同一课节的第二次生成」在 `题数.fill` 处 90s 超时。
- 链路实证（C++ 用例 error-context 快照）：打开 Coding Tools 时面板渲染的是上一用例留下的 ACTIVE set（`练习集合` 下拉显示 Java set、`100 分`、`4/4 通过`），生成表单未渲染，故 `题数.fill` 超时；且即便走「新建练习」，第二次生成的 item 与首份 set 的 item **stem 完全相同**，触发产品 novelty 去重（`practice_generation.py:386` `lifecycle_status != "deleted"`）→ `practice_duplicate`。
- 修复（`practice-tools.spec.ts` 内，真实 UI 流程）：新增 `clearExistingPracticeSets(page, panel)`——选课节后等「练习集合」picker 出现（=有既有 set）即用「删除集合」+ 确认对话框逐个删除（删除使 set 进入 `deleted`，被 novelty 先验排除），直到 picker 消失、生成表单出现。picker 作为「加载就绪」信号避开「加载中表单瞬时可见」的竞态。每个用例从此从干净生成表单起步。无 API 绕过、无 force click、无隐藏 Tutor。

### 17.4 三种 viewport 无重叠检查（任务包 §4）

用一次性探针（独立 `playwright.viewport.config.ts` + `_viewport_probe.spec.ts`，跑后即删，**不改 `playwright.config.ts` 矩阵**）对 seed 实跑 UI：每个 viewport 打开练习面板，取 `.practice-generate` 与 `.tutor-panel` 的 bounding box，断言不相交；并对 Java 复选框与「生成练习」按钮做 `trial` 点击（被覆盖即失败）。结果 **3 passed (4.6s)**：

| viewport | 列模式 | 断言 |
|---|---|---|
| 1280×720 | 两栏 | 左栏右沿 ≤ Tutor 左沿；无重叠；Java 复选框 + 生成按钮 trial 点击通过 |
| 1600×900 | 两栏 | 同上（更宽 track，收缩链更宽松） |
| 820×900 | 单列(<860) | `.tutor-panel` computed `position:static`，纵向下置于内容之后；无重叠 |

1280×720 亦由完整 9 项 browser-test 的真实点击（Java/C++ 复选框、生成按钮、交卷）覆盖。

### 17.5 完整 9 项 browser-test 结果（`scripts/browser-test.ps1`，受控 Compose + 双 seed + Chromium，1 worker）

**9 passed (42.2s)，0 failed，0 skipped**（seed `SEEDED Stage5 2B Browser aa6ec1`）：

| # | spec | 结果 |
|---|---|---|
| 1 | `app-shell.spec.ts` Tutor smoke | ok (3.1s) |
| 2 | practice Java：generate→answer→grade→run record | ok (8.3s) |
| 3 | practice C++：generate→answer→grade→run record | ok (8.3s) |
| 4 | practice science Wolfram required | ok (3.4s) |
| 5 | practice science negative（零 Wolfram） | ok (5.1s) |
| 6 | Tutor code required | ok (3.8s) |
| 7 | Tutor code negative（零 execution） | ok (2.8s) |
| 8 | Tutor Wolfram required | ok (3.8s) |
| 9 | Tutor Wolfram negative（零 science） | ok (2.8s) |

### 17.6 其余必跑验证（均如实，命令分开跑）

- `cd apps/web && npm run lint` → **0 errors, 7 warnings**（既有，未新增）。
- `cd apps/web && npm run build`（`tsc -b && vite build`）→ **built in 5.90s**（exit 0）。
- `scripts/system-test.ps1`（受控 Compose，真实 API+worker+Postgres+MCP）→ **11 passed in 19.25s**（`SYSTEM_TEST_EXIT=0`，种子修复后复跑，系统合同未受影响）。
- `bash -n scripts/browser-test.sh` / `bash -n scripts/system-test.sh` → **OK**。
- `git diff --check`（含新增文件 `git add -N`）→ **CLEAN，exit 0**（无空白/冲突标记）。
- Compose 残留资源：`docker ps -a/--network ls/--volume ls` 过滤 `ha_stage5_2b*` → **容器/网络/卷均为空**（`ha_stage5_2b`、`ha_stage5_2b_browser`、临时 `ha_stage5_2b_vp` 三 project 均已 `down --volumes --remove-orphans` 清空）。

### 17.7 本轮修改文件

- `apps/web/src/styles.css`（D：shrink-chain `min-width:0` 收缩链）。
- `apps/web/e2e/practice-tools.spec.ts`（B 单语言选择；E `clearExistingPracticeSets` 跨用例状态隔离）。
- `apps/web/e2e/tutor-tools.spec.ts`（C 合法 observation/计数断言；§16 的 90s/Locator 类型）。
- `tests/system/seed_browser_tools.py`（D：Qdrant payload 补 `document_id`，**人工授权的 test-only 修复**，零产品代码）。
- `docs/.../PART_2_SLICE_2B_BATCH_B_GLM_HANDBACK.md`（本节）。
- 一次性探针 `apps/web/e2e/_viewport_probe.spec.ts`、`apps/web/playwright.viewport.config.ts` 跑后已删除（未入 git）。
- 未改 `apps/api/**`、`playwright.config.ts`、schema/migration、worker、生成、评分、预算、prompt、工具决策、`docker-compose.yml`、stub、seed_browser_tutor。

### 17.8 给 Codex 的说明

- 种子 `document_id` 修复为人工授权范围外文件（`tests/system/seed_browser_tools.py`）的 test-only 1 行变更，已在本节如实标注；如需回退，仅删该字段即回到 `insufficient_evidence`。
- `clearExistingPracticeSets` 通过真实「删除集合 + 确认」UI 流程实现用例间隔离，等同真实用户重新生成课节；非绕过。

### 17.9 红线确认

- `remote_not_run` 仍阻止 Slice 2B 正式收尾（本轮未触真实 provider/Judge0/Wolfram Cloud）。
- 未 `commit`、未 `push`；未安装依赖；未读取或修改 `.tmp/`、`artifacts/`。
- 未运行 OCR（诊断依据为 Playwright `error-context.md` 文本快照与代码链路实证；test-results 截图仅辅助）。
- 未进入 Stage 5 第三部分。

完成后停止，交回 Codex。
