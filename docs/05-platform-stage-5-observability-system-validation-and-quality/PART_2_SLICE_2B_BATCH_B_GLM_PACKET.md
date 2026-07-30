# Stage 5 Part 2 Slice 2B Batch B GLM 实现任务包

## 1. 任务目标

Batch A 已于 2026-07-29 通过 Codex 独立验收。Batch B 在不修改产品质量合同的前提下，
把 Batch A 的高风险基线接入真实 API、Redis worker、Postgres、MCP client、受控后端和
Chromium，并接入普通 PR 的零付费 CI Gate。

本轮必须交付：

1. Java、C++ 各一条完整浏览器生成、作答、评分和运行记录路径；
2. scientific Practice 的 Wolfram required 与 zero-call negative 路径；
3. Tutor code MCP、Tutor Wolfram MCP 的 required 与 zero-call negative 路径；
4. 受控 Compose、确定性 seed/stub、系统断言和 CI Gate；
5. 安全聚合的 controlled baseline 结果，不得冒充真实 Judge0/Wolfram。

本轮不运行真实 provider、Judge0 或 Wolfram Cloud。Batch B 候选实现交回后，Codex 先独立
验收和组织 OCR，再单独取得人工批准运行真实远程 Gate。`remote_not_run` 仍阻止 Slice 2B 收尾。

## 2. 仓库与环境

- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- Shell：PowerShell
- Compose：`docker-compose.yml` + `compose.system-test.yml`
- Web：`apps/web` 既有 Playwright/Chromium
- CI：GitHub Actions `ubuntu-latest`
- 正式系统事实：Postgres；队列：Redis
- 普通 PR 不读取任何远程 secret，不产生 provider/Judge0/Wolfram 费用

开始前运行：

```powershell
git status --short --branch
```

保留全部既有 dirty files。不得读取或修改 `.tmp/`、`artifacts/`。

## 3. 必须完整读取

- `AGENTS.md`
- `docs/README.md`
- `docs/LEARNING_AGENT_BLUEPRINT.md`
- `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- Stage 5 `README.md`
- `specs/006-controlled-system-tests-and-ci-gates.md`
- `specs/007-high-risk-tool-and-practice-quality-baseline.md`
- `adr/003-controlled-test-boundaries-and-ci-gate-separation.md`
- `adr/004-durable-provider-call-facts-across-business-rollback.md`
- `PART_2_SLICE_2B_GLM_IMPLEMENTATION_PACKET.md`
- `PART_2_SLICE_2B_BATCH_A_GLM_HANDBACK.md`
- 本任务包

同时读取并复用：

- `compose.system-test.yml`
- `scripts/system-test.ps1` / `.sh`
- `scripts/browser-test.ps1` / `.sh`
- `tests/system/model_services_stub/**`
- `tests/system/test_tutor_vertical.py`
- `tests/system/seed_browser_tutor.py`
- `apps/web/playwright.config.ts`
- `apps/web/e2e/app-shell.spec.ts`
- `apps/api/tests/quality_baseline/**`
- `apps/mcp_execution/adapter.py`
- `apps/mcp_execution/mcp_execution_server.py`
- `apps/mcp_execution/fake_wolfram_server.py`

若实际产品入口与任务包冲突，停止冲突路径并报告；不得自行修改产品合同。

## 4. 全局边界

### 4.1 禁止

- 不修改 `apps/api/learn_platform_api/**` 产品代码；
- 不修改 ORM、migration、公开 API、Practice artifact、Job/Turn 状态或预算；
- 不提高 provider、repair、MCP、step、timeout 或题数上限；
- 不新增“编程题数量”，不允许每 Set 多个 specialized item；
- 不修改产品 prompt 迎合固定样本；
- 不增加关键词捷径、固定答案、固定题目或 test-only 产品分支；
- 不把 fake backend 写成 Judge0/Wolfram Cloud passed；
- 不保存 prompt、课程正文、题干、答案、代码、tests、compiler/Wolfram 原文、key、URL 或绝对路径；
- 不读取远程 key，不发起真实付费/远程调用；
- 不新增依赖，除非仓库 lockfile 已含且无需下载；发现缺依赖时报告；
- 不做 UI 重设计，不增加 Firefox/WebKit/移动/视觉快照矩阵；
- 不运行 OCR，不 commit，不 push，不进入 Stage 5 第三部分。

### 4.2 允许修改

- `compose.system-test.yml`
- `tests/system/**`
- `scripts/system-test.ps1` / `.sh`
- `scripts/browser-test.ps1` / `.sh`
- `apps/web/e2e/**`
- `apps/web/playwright.config.ts`（仅必要配置）
- `.github/workflows/ci.yml`
- `apps/api/tests/quality_baseline/**`（仅 Batch B runner/report 接线）
- test-only fake execution/Wolfram server；优先位于 `tests/system/**`
- 必要的 Dockerfile/test fixture/seed
- `.gitignore` 精确忽略新的测试结果目录
- Batch B handback

若必须修改 `apps/mcp_execution/**`，只允许增加 test server 启动入口或可注入 test factory，不得改变
正式 adapter/MCP 合同；先在 handback 中单列原因。

## 5. 受控 Compose

扩展 `compose.system-test.yml`，复用 base Compose 服务，并为测试环境提供：

- `practice-worker`
- `tutor-system-worker`
- `code-lab-worker`（仅实际浏览器路径需要时）
- `capability-probe`
- `mcp-execution`
- test-only fake execution backend
- test-only fake Wolfram MCP server
- model-services stub
- system-test runner
- Web

要求：

1. 所有 provider/embedding URL 指向 model-services stub；
2. execution adapter 只指向 fake execution backend，不指向 Judge0；
3. Wolfram URL 只指向 fake Wolfram MCP，不指向 `agenttools.wolfram.com`；
4. API 不获得 Wolfram key；只允许需要它的 worker/probe获得 test-only 空值或占位值；
5. fake 服务不发布公网端口，除非 runner 必须访问；优先 Compose 内网；
6. 数据卷和网络由唯一 Compose project 隔离，结束必须 `down --volumes --remove-orphans`；
7. readiness 必须轮询健康/状态，不使用固定 sleep 冒充；
8. fake services 暴露安全的 reset/counters endpoint，只返回场景、调用计数和稳定分类，不返回请求正文；
9. scenario reset 与调用计数必须原子，避免 Slice 2A 曾出现的 reset race；
10. Compose 环境中不得出现真实 secret 名值或远程默认 URL 的意外回退。

fake execution backend 至少确定性支持 Python/Java/C++ 的：

- accepted；
- compile error；
- wrong-output/test mismatch 所需返回；
- timeout/infra failure（只用于系统反事实）。

fake Wolfram 至少支持：

- `WolframAlpha`、`WolframContext` 固定 schema；
- required success；
- invalid result / connection-style failure；
- 调用计数；
- negative 场景零调用证明；
- 永不暴露 `WolframLanguageEvaluator`。

## 6. Model Stub 与固定场景

扩展既有 `tests/system/model_services_stub`，不得新建第二套 provider stub。

固定场景必须通过显式 test scenario/reset 选择，不得按用户文本关键词猜测：

- `practice_java_success`
- `practice_cpp_success`
- `practice_science_wolfram_required`
- `practice_science_negative`
- `tutor_code_required`
- `tutor_code_negative`
- `tutor_wolfram_required`
- `tutor_wolfram_negative`

每个场景的 provider 调用 ordinal 和响应序列必须锁定，并保留 Slice 2A Tutor
success/repair/timeout 合同。新增场景不得改变旧场景结果。

固定 provider artifact 只存在 test stub 内，不进入报告或浏览器失败输出。不得把固定场景当作
产品 prompt/意图正确性的证明；它只验证系统接线、状态、MCP 和 UI。

## 7. Seed 与系统事实断言

新增或扩展 seed 脚本，创建最小脱敏工作区、课程、课节、材料版本和 capability authorization。
必须使用公开 API 或明确的 test seed 边界；不得直接伪造完成后的 AgentRun、ProviderCall、
AgentToolCall、PracticeSet、Attempt 或 Tutor Turn。

系统测试必须从 API 或新 Postgres Session 核验：

- Job/Turn/Attempt 最终状态；
- Set/Item/feedback 实际存在；
- Java/C++ interaction language 正确且互不替代；
- AgentRun owner/role 正确；
- ProviderCall phase/ordinal/status 与 stub outbound 次数一致；
- AgentToolCall 工具名、状态与 owner 正确；
- required 场景 Tool 实际调用一次或合同规定的精确次数；
- negative 场景即使已授权也为零调用；
- Wolfram required 必须走 `WolframAlpha` 或 `WolframContext`；
- forbidden `WolframLanguageEvaluator` 为零；
- 预算不超过现有上限；
- 无半成品和跨 workspace 事实；
- controlled/remote 标签明确为 `controlled_backend` / `remote_not_run`。

不得只断言 mock 调用次数；关键事实必须从最终数据库/API读取。

## 8. Chromium 浏览器路径

新增独立 spec 文件，避免把所有场景继续堆进 `app-shell.spec.ts`。建议：

- `apps/web/e2e/practice-tools.spec.ts`
- `apps/web/e2e/tutor-tools.spec.ts`

### 8.1 Java 与 C++

Java、C++ 各一条完整路径：

1. 进入已 seed 的工作区和课程；
2. 打开课节“练习”；
3. 新建练习；
4. 总题数选择 `1`；
5. 题型选择“要求编程题”；
6. 勾选代码执行授权；
7. 只选择当前目标语言；
8. 同意外部模型生成；
9. 生成并等待 Job 终态；
10. 验证题目类型为编程且语言分别为 Java/C++；
11. 填入受控正确答案；
12. 提交并等待评分终态；
13. 验证自动测试反馈和分数/判定；
14. 打开运行记录，验证练习生成、评分和 Tool Call/Provider Call 下钻事实。

不得只 seed 已完成 PracticeSet 绕过生成，也不得通过直接 API 提交代替浏览器作答。

### 8.2 Scientific Practice

- required：生成科学计算题，授权 Wolfram，证明 fake Wolfram counter 增加、Tool Call succeeded、
  Set 发布、浏览器可见工具状态，并完成一次作答/评分；
- negative：使用工具不必要样本，即使已授权也必须零 Wolfram 调用，不出现伪 Tool Call。

### 8.3 Tutor

- code required：授权 code MCP，模型显式请求，Tool Call succeeded，回答与运行记录完成；
- code negative：已授权但模型不请求，零 execution 调用；
- Wolfram required：授权 science MCP，调用 allowlisted Tool，回答包含正常结果/非 limitation，
  运行记录完整；
- Wolfram negative：已授权但模型不请求，零 Wolfram 调用。

不得用普通问答是否“好看”代替 Tool 事实。

### 8.4 Playwright 质量

- 使用 role/label/可见文本定位，不使用脆弱 CSS 路径；
- 无固定 sleep；等待 HTTP response、Job 状态或可见终态；
- API 失败断言必须包含 status 和经过脱敏的 response body；
- dialog handler 必须 await；
- 每个场景隔离 reset，测试可独立运行；
- request sequence/late response 不得污染下一场景；
- 失败时保留 Playwright trace/screenshot/video 的现有策略，但不得把敏感正文上传 artifact；
- Chromium only。

## 9. 受控 Baseline 输出

复用 Batch A `RunRecord`/安全序列化，不创建第二套报告 schema。

系统/浏览器 runner 可输出一个安全 JSON summary 到测试结果卷，至少包含：

- stable sample/scenario ID；
- capability/language/mode/总题数；
- controlled layer；
- final status；
- tool requested/authorized/called/succeeded；
- provider/MCP/repair 计数；
- 稳定失败阶段；
- `remote_not_run`。

不得输出题干、回答、代码、tests、prompt、原始 response、URL、路径或 secret。
报告生成失败必须使 Gate 失败，不得静默跳过。

## 10. 脚本

扩展 `.ps1` 与 `.sh`，二者行为必须等价：

- 一个 controlled system 命令完成 Compose 构建、readiness、系统测试、报告、清理；
- 一个 browser 命令完成 seed、Chromium tests、报告、清理；
- 退出码真实传播；
- trap/finally 始终从仓库根清理；
- 并行或重复运行使用唯一 project/port/result 路径；
- 不依赖调用者当前目录；
- 不使用固定 sleep；
- 任何 service/环境缺失为 `environment_failed`，不能 skip；
- 不读取 `.env` 中的远程 key；显式覆盖所有远程 URL。

若现有 `system-test.*` / `browser-test.*` 扩展后过于混杂，可增加 Slice 2B 专用脚本，但不得复制
大量 Compose 生命周期逻辑。

## 11. CI

更新 `.github/workflows/ci.yml`：

1. Batch A compiler/baseline Gate 在 `ubuntu-latest` 运行；
2. controlled system Gate 运行 Practice/Tutor 双 MCP；
3. browser-smoke 运行 Java/C++、scientific Practice、Tutor code/Wolfram；
4. 普通 PR 不读取远程 secrets；
5. 环境缺失/编译器缺失/Postgres 不可达不得 skip；
6. 保留现有 Web、API、Tutor Slice 2A、orchestration Gate；
7. 控制总耗时，避免同一 132 项 baseline 在多个 job 重复全跑；
8. 上传的 artifact 只能是安全报告、JUnit 与 Playwright 脱敏结果；
9. CI 中不得出现 `continue-on-error: true` 或失败吞噬。

建议把纯 contract/report 测试放 `api-focused`，compiler/budget/PG baseline 放一个独立
`quality-baseline` job；具体划分以不重复昂贵 Compose 为准。

## 12. 必须新增的反事实

至少证明：

- Java artifact 被错误标为 Python/C++ 时浏览器或系统 Gate 失败；
- C++ compile failure 不发布 Set；
- required Wolfram 场景 provider 未请求 Tool 时归类 `tool_request_missed`；
- Tool requested 但 fake MCP 未调用时 Gate 失败；
- fake Wolfram invalid schema 不发布伪验证 Set；
- capability 未 ready 时强制专业题失败；
- 已授权 negative Tutor/Practice 仍零调用；
- 工具失败时 Tutor 显示 limitation，不宣称已验证；
- fake service counter 未 reset 或跨场景污染时测试失败；
- 报告试图加入 forbidden field 时 Gate 失败。

反事实可主要放系统测试，不要求为每项增加浏览器用例。

## 13. 验证

按从窄到宽执行并报告精确结果：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/quality_baseline/
```

运行新增 system focused tests，然后：

```powershell
.\scripts\system-test.ps1
.\scripts\browser-test.ps1
```

再运行：

```powershell
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
docker compose -f docker-compose.yml -f compose.system-test.yml config
git diff --check
```

若 `.sh` 无可用 Linux/WSL 环境，至少运行：

```powershell
bash -n scripts/system-test.sh
bash -n scripts/browser-test.sh
```

并在 handback 如实说明未做 Linux 端到端；不得写成通过。

所有 Compose 测试结束后确认无残留本 Slice project/container/volume。

## 14. 强制 Handback

生成：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2B_BATCH_B_GLM_HANDBACK.md`

必须包括：

- 实际修改文件；
- Compose service/网络/secret 边界；
- 八个固定场景的 stub ordinal 合同；
- Java/C++ 浏览器步骤和真实数据库事实；
- Practice/Tutor required/negative Tool 事实；
- counter/reset 隔离方式；
- controlled baseline 报告样例字段，不得贴正文；
- CI job 与预计时间；
- 每条验证命令、passed/failed/skipped、耗时；
- 未运行项和环境条件；
- `remote_not_run` 明确阻止 Slice 完成；
- 第三部分候选失败分布，但不在本轮修复；
- 未 commit、未 push、未 OCR、未调用真实远程服务的确认。

完成后停止，等待 Codex 独立验收。不得自行运行真实 provider/Judge0/Wolfram，不得进入第三部分。
