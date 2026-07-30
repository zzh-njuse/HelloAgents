# Stage 5 Part 2 Slice 2B — OCR Fix GLM Handback

状态：OCR 修正轮实现候选交回，等待 Codex 独立验收。**`remote_not_run`，因此
Slice 2B 仍未正式收尾。**

日期：2026-07-30

执行者：GLM（实现），在 `PART_2_SLICE_2B_OCR_FIX_PACKET.md` 的授权范围与已接受
Spec 006 / Spec 007 / ADR 003 / ADR 004 合同内工作。

## 0. 交回结论摘要

本轮只关闭任务包列出的 Slice 2B OCR 高可信问题（Fix 1–8），严格遵守允许文件范围，
不处理任务包 §5 明确拒绝或暂缓的 OCR 评论，不扩大到 Remote Gate 或第三部分。

- 全部 8 项修复落地，均落在任务包 §3 允许修改的文件内（外加 1 个同目录极小
  focused test 文件，见 §3.1 理由）。
- 未修改任何 `apps/api/learn_platform_api/**` 产品代码、schema、migration、API route、
  worker、Practice/Tutor 生成策略、Compose、CI、依赖、`docker-compose.yml` 或远程配置。
- 全部验证实跑通过：quality baseline 153/0/0、system Gate 11/0/0、Web lint 0 error /
  build ok、browser Gate 9/0/0、focused stub 契约 6/0/0、`git diff --check` clean、
  Compose 容器/网络/卷全部清理。
- **`remote_not_run`**：未调用真实 provider/Judge0/Wolfram Cloud，未把受控后端写成
  真实远程已通过。

## 1. 实际修改 / 新增文件

| 文件 | 性质 | 本轮改动 |
|---|---|---|
| `apps/api/tests/quality_baseline/report.py` | test-only（Batch A） | Fix 1：分类器新增 `tool_call_missed`/`forbidden_tool_called` 两个合同违例类别，required 未调用与 forbidden 被调用不再落入成功分类；既有 authorization→capability→schema→connection→result→reference→artifact 优先级不变。Fix 2a：`ALLOWED_SNAPSHOT_KEYS` 改为人工维护的显式字面 `frozenset`，不再由 `asdict` 自动生成 |
| `apps/api/tests/quality_baseline/controlled.py` | test-only（Batch A） | Fix 2b：`_ABS_PATH_RE` 正则替换为等价的 `_redact_paths()`（`_path_end` 扫描），完整遮蔽含空格 Windows 路径、Windows `/` 与 `\` 两种分隔、含空格 POSIX 路径；POSIX 根仅在 token 边界匹配（`input/output`、`3/4` 不误删）；`<path>` 输出合同与长度上限不变 |
| `apps/api/tests/quality_baseline/test_report_contract.py` | test-only（Batch A） | Fix 1/2a 测试：新增两类别 `CATEGORY_FACTS`、全分支表驱动 `_CONTRACT_TABLE`（required/optional/forbidden × 调用/未调用 + 优先级反例）、`forbidden_called_never_success`、`required_uncalled_never_success`、优先级测试；显式白名单 `in_sync_with_runrecord` + `future_sensitive_field_is_not_auto_whitelisted`（子类携带未来敏感字段被白名单丢弃） |
| `apps/api/tests/quality_baseline/test_budget_curve.py` | test-only（Batch A） | Fix 3：重写 `test_budget_settings_are_not_modified`——不再比较两个独立 `Settings()` 默认实例（假阳性），改为 spy 捕获实际传入 `execute_generation()` 的 settings 对象、执行前后断言同一对象关键预算字段未变（`max_provider_calls==4`、`max_attempt_steps==12`）；1/3/5/10 矩阵、最终题数、step、失败分类断言未降低；移除因重写而未用的 `Settings` import |
| `apps/api/tests/quality_baseline/test_controlled_env.py` | test-only（Batch A） | Fix 2b 测试：含空格 Windows 路径、Windows `/` 与 `\` 两种形式、含空格 POSIX 路径、POSIX 根边界、普通诊断文本不整段误删、`_redact` 长度上限/`<path>` 合同 6 项 |
| `tests/system/fake_execution_backend/server.py` | test-only（Batch B） | Fix 4：`_next_count()` 在同一 `LOCK` 临界区读取 `ACTIVE_SCENARIO` 并递增该场景计数，返回 `(scenario, count)`；`/submissions` 只使用该次原子快照，不再二次读取全局 `ACTIVE_SCENARIO`。既有 reset、call counter、Accepted/compile/runtime/timeout/infra_failure 合同不变 |
| `tests/system/model_services_stub/server.py` | test-only（Batch B） | Fix 5：`ordinal > len(SCENARIO_RESPONSES[scenario])` 时返回稳定、可诊断、不含 prompt/secret 的 HTTP 409（`stub_scenario_exhausted` + scenario/ordinal/sequence_length），不再重复最后一个响应。Slice 2A `success/repair/timeout/failure` 与 Slice 2B 八类场景合同不变 |
| `tests/system/test_stub_contracts.py` | **新增** test-only focused（见 §3.1） | Fix 4/5 契约测试（6 项）：fake exec `_next_count` 返回值、场景切换不串计数、并发/交错 reset 竞态反例（per-scenario 计数连续无洞）；model stub 正常序列不变、首次超额 409、超额不伪装末响应 |
| `tests/system/test_practice_vertical.py` | test-only（Batch B） | Fix 8：临时 `httpx.Client` 改为 `with _client() as c:` context manager 关闭（不再泄漏未关闭连接） |
| `tests/system/test_tutor_tools_vertical.py` | test-only（Batch B） | Fix 8：Tutor Wolfram negative 在调用前显式断言 `fake_wolfram_calls("success")==0` 基线，再断言调用后仍为 0。未改精确 stub token usage、未删 fake counter isolation 反例 |
| `apps/web/src/app/TutorPanel.tsx` | 产品 Web（已 M） | Fix 6：① capability ready→unavailable 时自动清零 `scienceToolAuthorized`/`codeToolAuthorized`（无 disabled-but-checked）；② `refreshSessions()` 与学习记忆/完成记录加载加 `mountedRef`+`activeContextRef`/`cancelled` 守卫，旧 workspace/旧课程/卸载后晚到响应不写回；③ `createTutorTurn` 成功后立即消费/清理幂等键（先于 session 读取），创建失败保留 key、成功后读取失败不复用已消费 key。EventSource + 2.5s 有界轮询 + 120s 上界未动 |
| `apps/web/e2e/app-shell.spec.ts` | test-only（Batch B） | Fix 7：首次提交确认对话框改为与 click 同步的 `waitForEvent("dialog")` + 断言 `type()==="confirm"`，dialog 必须出现才通过；handler 随该 click 消费，不残留 |
| `apps/web/e2e/practice-tools.spec.ts` | test-only（Batch B） | Fix 7：`clearExistingPracticeSets` 循环每次删除用 `Promise.all([waitForEvent("dialog"), click])` 同步等待并断言 dialog 出现，handler 逐次消费不跨迭代/跨操作残留；不增加固定 sleep、不 API 直删、UI 删除与最终状态断言不降级 |
| `docs/.../PART_2_SLICE_2B_OCR_FIX_GLM_HANDBACK.md` | 本 handback | 本文档 |

未触：`apps/api/learn_platform_api/**`（含 `provider_call_recorder.py`、生成/评分/worker）、
schema/migration、`apps/mcp_execution/**`、`docker-compose.yml`、Compose、CI、依赖、
`playwright.config.ts`、`tutor-tools.spec.ts`、`package-lock.json`、stub seed、真实远程配置。

### 1.1 新增 focused test 文件理由（任务包 §3）

`tests/system/test_stub_contracts.py` 是同目录（`tests/system/`）下的极小 focused
test 文件，理由：

- Fix 4（fake exec 原子性）与 Fix 5（stub 超额失败）是 **stub server 逻辑** 的纯单测，
  不需要 Postgres/Redis/MCP/浏览器，按进程内 import + 本地 loopback HTTP 即可确定性验证。
- system-test-runner 的 Compose 命令显式只收集 `test_practice_vertical.py` 与
  `test_tutor_tools_vertical.py` 两个文件（见 `compose.system-test.yml`），因此新增该
  文件**不进入 system Gate**，保证 system Gate 仍为精确 11；它作为 focused 验证单独运行。
- 不引入产品代码依赖、不连任何远程服务；只 `importlib` 加载同目录两个 server 模块。

## 2. Fix 1–8 逐项结果

### Fix 1：科学工具分类覆盖合同违例 ✓

`report.py::classify_science_tool_run` 新增两条优先级分支，二者均为稳定合同违例类别，
不计入成功分类：

- `expectation == "forbidden" and called` → `forbidden_tool_called`（在所有成功分类
  之前判定，即便下游 result/reference/artifact 全部成功也不得返回 `succeeded_*`）。
- required 样本 `requested + authorized + capability_ready` 但 `called == False` →
  `tool_call_missed`（执行缺口），不得落入 `succeeded_without_wolfram`。
- required 未请求仍为 `tool_request_missed`（既有）。
- authorization → capability → schema → connection → invalid result → reference →
  artifact 的既有相对优先级**未漂移**（`test_classifier_priority_authorization_before_capability_before_call`
  与 `_CONTRACT_TABLE` 覆盖）。

`SCIENCE_CATEGORIES` 显式新增这两类（带注释标注为 OCR-fix 合同违例类别，非成功状态）。
`test_classifier_reaches_every_category` 因此也覆盖两类。新增 `_CONTRACT_TABLE` 表驱动
覆盖 required/optional/forbidden × 调用/未调用反例 + 优先级反例。

### Fix 2：显式快照白名单 + 绝对路径脱敏 ✓

**2a 白名单**：`ALLOWED_SNAPSHOT_KEYS` 由 `frozenset(asdict(RunRecord(...)).keys())`
改为人工维护的显式 `frozenset({...})` 字面量（按 Identity/Item/Tool/Stage/Provider/
Counts/Failure/Cost 分组注释）。`serialize()` 仍 `asdict` 后按白名单过滤；新增
`test_allowed_snapshot_keys_in_sync_with_runrecord`（对当前字段保持完整、但不由字段
自动生成——新增字段会令该断言失败而非自动入白名单）与
`test_future_sensitive_field_is_not_auto_whitelisted`（子类携带一个良性命名的未来敏感
字段 `internal_debug_blob`，序列化后被白名单丢弃，证明白名单独立于 dataclass 字段）。

**2b 路径脱敏**：旧 `_ABS_PATH_RE` 正则 `(?:[A-Za-z]:\\|/)[^\s\"'<>|]*` 在空格处截断
且不认 `C:/`。替换为等价的 `_redact_paths()`（`_path_end` 扫描）：

- Windows 根 `[A-Za-z]:[\\/]` 同时认 `C:\` 与 `C:/`；
- POSIX 根 `(?<![A-Za-z0-9])/` 仅在 token 边界（行首或非字母数字后）匹配，故 `input/output`、
  `3/4` 不被误删；
- 路径体内的空格仅当其后续 run 仍含分隔符（属于路径的分隔层级，如 `Program Files\app`）
  才吸收，普通诊断文本（空格分隔词、无分隔符）不整段误删；
- `<path>` 输出合同与 `_DIAG_LIMIT=400` 长度上限不变。

6 项脱敏测试覆盖含空格 Windows、Windows `/` 与 `\`、含空格 POSIX、POSIX 边界、普通文本
不误删、`_redact` 长度上限/`<path>` 合同。

### Fix 3：预算设置测试观察真实执行对象 ✓

`test_budget_settings_are_not_modified` 重写：删除比较两个独立 `Settings()` 默认实例的
假阳性写法（从不观察执行）。改为 `monkeypatch` spy 包裹 `execute_generation`，捕获实际
传入的 settings 对象（`captured["settings"] is settings` 证明同一对象），在执行体前快照
`_budget_snapshot`（`max_provider_calls`/`max_attempt_steps`/`max_searches`），执行后对
**同一对象**断言不变，并断言 `==4`/`==12`。1/3/5/10 矩阵、最终题数、step count、失败
分类断言均未降低（属其它既有测试，未触）。移除因重写而未用的 `Settings` import。

### Fix 4：fake execution 场景与计数原子一致 ✓

`fake_execution_backend/server.py::_next_count()` 参照 model-services stub 的
`_next_call()` 模式：在同一 `LOCK` 临界区读取 `ACTIVE_SCENARIO` 并递增该场景计数，返回
`(scenario, count)`。`/submissions` 只使用该次原子快照决定 `infra_failure` 分支与执行，
**不再二次读取全局 `ACTIVE_SCENARIO`**（消除“计入 A 却按 B 返回”的 Slice 2A reset race）。
既有 reset、call counter、Accepted/compile/runtime/timeout/infra_failure 合同不变。

`test_stub_contracts.py` 新增并发/交错 reset 反例：8 线程各 300 次 `_next_count` 与一个
在 `LOCK` 下切换 A/B 的 switcher 并发；断言无重复 `(scenario,count)`、每场景计数恰为
`{1..K}` 连续无洞（洞即意味着某次计数被错记到另一场景）。

### Fix 5：provider stub 超额调用显式失败 ✓

`model_services_stub/server.py`：当 `ordinal > len(SCENARIO_RESPONSES[scenario])` 时返回
HTTP 409 `{"error":"stub_scenario_exhausted","scenario":...,"ordinal":...,"sequence_length":...}`，
稳定、可诊断、不含 prompt/secret/key/URL；不再 `min(ordinal-1, len-1)` 重复末响应。Slice 2A
`success/repair/timeout/failure`（走 `_chat_content`）与 Slice 2B 八类场景合同不变——各合法
流程 provider 调用数 ≤ 序列长度（system Gate 11/0/0 实证未触发超额）。系统测试中 provider
调用次数仍用精确断言（如 `["plan","generation"]`）。

`test_stub_contracts.py` 新增：正常序列逐 ordinal 返回锁定内容且计数精确；首次超额明确 409
且 body 无敏感串；超额响应不伪装为末响应。

### Fix 6：Tutor 授权、异步状态与幂等键可恢复 ✓

`TutorPanel.tsx` 窄修（EventSource + 2.5s 轮询 + 120s 上界未动）：

1. capability `ready→unavailable`：新增两个 effect，不可用时自动
   `setScienceToolAuthorized(false)`/`setCodeToolAuthorized(false)`，杜绝 disabled-but-checked；
   `submit()` 既有提交前 `refreshCapabilities()` 复核保留。
2. `refreshSessions()` 与学习记忆/完成记录加载防旧 workspace/旧课程/卸载写回：新增
   `mountedRef`（卸载置 false）+ `activeContextRef`（每 render 更新当前 workspace/course/
   version）；`refreshSessions` 捕获调用时 context，晚到响应若 context 已变或已卸载则丢弃
   且不抛旧错误；记忆/完成 effect 用 `let cancelled` + cleanup 守卫。refs 不入任何 effect
   依赖数组，无依赖环。
3. `createTutorTurn` 成功后立即 `turnIdempotencyKey.current = null`（先于 session 读取）：
   创建失败则 catch 保留 key 供同次用户操作安全重试；创建成功但随后读取失败时，下次提交
   生成新 key，不复用已消费 key。

`mutateTurn`/`removeTurn` 的直接 `fetchTutorSession` 未额外加守卫——任务包 Fix 6.2 指定
范围是 `refreshSessions()` 与学习记忆/完成记录加载，二者已覆盖；这些是同步用户动作，staleness
风险低，未扩大范围。

### Fix 7：浏览器确认对话框成为真实断言 ✓

- `app-shell.spec.ts`：首次提交确认对话框改为 `Promise.all([page.waitForEvent("dialog",
  {timeout:10_000}).then(assert type==="confirm" + accept), click()])`，dialog 必须出现才
  通过，且随该 click 消费、不残留。
- `practice-tools.spec.ts::clearExistingPracticeSets`：循环每次删除用同样同步
  `waitForEvent("dialog")` 等待并断言 dialog 出现，handler 逐次消费，不跨迭代/跨操作残留；
  无固定 sleep、不 API 直删、UI 删除与最终状态断言不降级。
- `tutor-tools.spec.ts`：按任务包 §7 未修改（OCR 关于 `fill()` 触发确认框的猜测无浏览器
  反例证据；且该文件不在本轮允许修改清单）。

### Fix 8：小型测试资源真实性修正 ✓

- `test_practice_vertical.py`：临时 `httpx.Client` 改 `with _client() as c:` 关闭。
- `test_tutor_tools_vertical.py`：Tutor Wolfram negative 调用前显式断言基线
  `fake_wolfram_calls("success")==0`，再断言调用后仍为 0。
- 未把精确 stub token usage 改成 `> 0`（这些是 Provider Call 事实合同）；未删 fake counter
  isolation 反例（`test_counter_isolation_between_scenarios` 保留，层级为 fake wolfram
  跨场景计数隔离）。

## 3. 新增测试

| 测试 | 文件 | 覆盖 |
|---|---|---|
| `_CONTRACT_TABLE`（9 分支）+ `forbidden_called_never_success` + `required_uncalled_never_success` + 优先级 | `test_report_contract.py` | Fix 1 全分支 + 优先级 |
| `test_allowed_snapshot_keys_in_sync_with_runrecord` + `test_future_sensitive_field_is_not_auto_whitelisted` | `test_report_contract.py` | Fix 2a 显式白名单 |
| 6 项路径脱敏 | `test_controlled_env.py` | Fix 2b 三类路径 + 边界 + 不误删 |
| `test_budget_settings_are_not_modified`（重写） | `test_budget_curve.py` | Fix 3 真实对象不变性 |
| fake exec 原子性 3 项（返回值 / 隔离 / 竞态） | `test_stub_contracts.py` | Fix 4 |
| model stub 超额 3 项（正常序列 / 首次超额 409 / 不伪装末响应） | `test_stub_contracts.py` | Fix 5 |

不以源码字符串检查替代行为测试。

### 3.1 Tutor 手工 smoke 步骤（任务包 §6.7，无 Web 测试运行器）

1. **capability 失效（Fix 6.1）**：在 science/code capability ready 的 workspace，勾选
   “允许本次使用科学工具”；令 capability 变为 unavailable（停 capability probe / 关 MCP 使
   投影翻为 unavailable）。预期：复选框自动取消勾选（disabled-but-checked 不复存在）；
   重新可用后保持未勾选（需用户重新授权）。
2. **成功创建后读取失败（Fix 6.3）**：提交一个 Tutor Turn，待 `createTutorTurn` 成功后，
   在 devtools 阻断随后的 GET session 请求使其失败。预期：Turn 已创建（运行记录可见）；
   再次提交生成**新** Turn（已消费的幂等键不被复用，无重复重试 Turn）。

## 4. 每条验证命令的独立结果（实跑，命令分开、未相加冒充）

环境：仓库 `.venv`（Python 3.12.13，pytest 8.4.2，psycopg 3.3.4）；Postgres
`localhost:55432`；Docker 28.5.1 + Compose v2；Node 24；本机 javac 21 / g++ 16.1。

1. focused（纯数据，.venv）：
   `.venv\Scripts\python.exe -m pytest -q apps/api/tests/quality_baseline/test_report_contract.py apps/api/tests/quality_baseline/test_controlled_env.py`
   → **87 passed in 0.97s**（含 Fix 1 分类器表 + Fix 2a 白名单 + Fix 2b 脱敏）。
2. focused stub 契约（.venv，进程内 + loopback，无 Compose）：
   `.venv\Scripts\python.exe -m pytest -q tests/system/test_stub_contracts.py`
   → **6 passed in 2.09s**（Fix 4 原子性/竞态 + Fix 5 正常边界/超额 409）。
3. quality baseline（.venv，隔离 Postgres）：
   `.venv\Scripts\python.exe -m pytest -q apps/api/tests/quality_baseline`
   → **153 passed, 0 failed, 0 skipped in 137.97s**。
4. system Gate（Compose，真实 API+worker+Postgres+MCP）：
   `.\scripts\system-test.ps1`
   → **11 passed in 19.29s**（`EXIT_CODE=0`；runner 显式只收集两个 vertical 文件，故新增
   `test_stub_contracts.py` 不计入 11）。
5. Web lint：`cd apps/web && npm.cmd run lint` → **0 errors, 7 warnings**（既有，TutorPanel
   改动未新增 warning）。
6. Web build：`cd apps/web && npm.cmd run build`（`tsc -b && vite build`）→ **built in 4.62s**
   （exit 0；TutorPanel 改动通过类型检查）。
7. browser Gate（Compose + Chromium + 双 seed）：
   `.\scripts\browser-test.ps1` → **9 passed (42.0s)**（`EXIT_CODE=0`；seed
   `SEEDED Stage5 2B Browser de883a`；app-shell/practice-tools dialog 真实断言通过）。
8. `git diff --check`（含新增文件 `git add -N`）→ **CLEAN，exit 0**。
9. Compose 残留：`docker ps -a/--network ls/--volume ls` 过滤 `ha_stage5_2b*` →
   **容器/网络/卷均为空**（system 与 browser 两 project 均 `down --volumes --remove-orphans`）。

## 5. 未采纳 OCR 评论及理由（任务包 §5）

均**未实现**，遵循任务包 §5：

- 不降级 `actions/checkout@v6`/`setup-node@v6`/`setup-python@v6`/`upload-artifact@v5`：这些
  版本真实存在，OCR 用了过期知识。
- 不删除 Compose `!reset`/`!override`：当前 Compose 已真实解析、构建并通过 system/browser
  Gate（本轮 11/0/0、9/0/0 实证）。
- 不把 CI 临时 Postgres 密码迁入 secret：隔离服务的非生产固定凭据。
- 不修改 4 维 Qdrant seed：`compose.system-test.yml` 显式设置 `PRODUCT_EMBEDDING_DIMENSION=4`。
- 不修改 `seed_browser_tutor.py` 导入：浏览器 Gate 已真实运行（9/0/0）。
- 不新增 uvicorn 依赖：fake Wolfram 镜像已真实构建与启动。
- 不处理嵌套 ternary、颜色、Safari 前缀、CSS 类命名、timeout 常量、未使用 import 等
  Low/nit（含未顺带处理 OCR 可能提的其它 Low）。
- 不改 `package-lock.json`：OCR 未审该生成文件，`npm ci`/lint/build 是其验证边界。
- 不增加真实 provider/Judge0/Wolfram 调用，不开始 Remote Gate。

## 6. 未解决问题与是否需要 Codex 裁定

- 无合同冲突、无越界修复、无环境阻断。全部 Fix 1–8 在允许范围内闭环，且全部验证实跑通过。
- **路径脱敏的内在歧义（说明，非阻断）**：含空格的**末段**路径组件（其后无分隔符也无行尾，
  如孤立 `/a/b/my dir`）与“路径 + 同行散文”在局部不可区分；`_redact_paths` 选择“仅当后续
  run 含分隔符才吸收空格”，因此完全遮蔽含空格**中间**组件（编译器实际形态，如
  `C:\Program Files\app\bin\tool.cpp`），而孤立末段空格组件会遮蔽到最后一个分隔符。该选择
  以“不整段误删诊断文本”为优先，已由 6 项测试固化。如 Codex 认为需更强覆盖孤立末段空格路径，
  可再裁定（不属本轮 OCR 高可信范围）。
- **手工 smoke 未执行（说明）**：Fix 6.1/6.3 的 UI 行为按任务包 §6.7 以手工 smoke 步骤写入
  handback（§3.1）；本轮未在真实浏览器手动演练 capability 失效与 create-then-read-failure
  两步（自动化层已由 lint/build/browser 9 项覆盖，且 Fix 6 未引入新 UI 交互）。如 Codex 要求
  人工浏览器复核这两步，可安排。

## 7. `remote_not_run`

本轮**未调用**真实 provider / Judge0 VM / Wolfram Cloud MCP。全部为受控 provider / fake
execution backend / fake Wolfram（`controlled_backend=true`），未把 fake 写成真实远程已通过。
真实远程 Gate 仍由 Codex 在人工批准后单独触发；**`remote_not_run` 阻止 Slice 2B 正式收尾**。

## 8. 声明

- 未 `commit`、未 `push`。
- 未运行 OCR。
- 未进入真实远程 Gate，未进入 Stage 5 第三部分。
- 未读取或修改 `.tmp/`、`artifacts/`、`.env`、真实 provider 配置或用户上传资料。
- 未安装依赖（仅用仓库 `.venv`/既有 Docker/Node）。
- 未修改 `apps/api/learn_platform_api/**` 产品代码、schema、migration、API route、worker、
  生成/评分策略、Compose、CI、依赖、`docker-compose.yml` 或真实远程配置。
- 报告与诊断不保存 prompt、题干、答案、代码、tests、compiler/Wolfram 原文、密钥、URL 或
  绝对路径（Fix 2 白名单 + 禁止字段防线 + 路径脱敏 + 对应测试）。

完成后停止，交回 Codex 独立验收。
