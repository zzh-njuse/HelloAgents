# Stage 5 Part 2 Slice 2A — OCR 修正 GLM Handback

状态：六项 OCR 高置信修正完成

日期：2026-07-29

任务包：`PART_2_SLICE_2A_OCR_FIX_PACKET.md`

本 handback 对应 OCR Fix Packet 的第 7 节。仅修改任务包第 3 节允许的测试、stub、
Playwright 与测试脚本；未触碰产品代码、Provider Call 语义、业务 orchestration、
schema、migration 或公开合同。

## 1. 六项修复逐项对应的文件与行为

### Fix 1：Linux 浏览器脚本从仓库根目录清理 — `scripts/browser-test.sh`

- 行为：Playwright 调用（`cd apps/web` + `npm run test:e2e`）整体放入子 shell
  `( ... )`。子 shell 内的 `cd` 不影响父 shell 工作目录，因此脚本结束/退出时
  EXIT trap 仍在仓库根目录执行，能定位 `docker-compose.yml` 与
  `compose.system-test.yml`。
- 保留：既有 cleanup trap（`trap cleanup EXIT INT TERM`）不动；`set -eu` 仍传播
  子 shell 的非零退出码。
- 说明：任务包第 6 节的验证命令运行的是 `browser-test.ps1`，其本身使用
  `Push-Location`/`Pop-Location`，工作目录已正确。`.sh` 是并行修正，按 Fix 1
  要求修复 bash 变体的同名问题，已通过代码审查确认子 shell 逻辑正确
  （§5 未对其单独跑端到端，原因见 §3）。

### Fix 2：stub 场景读取与计数递增原子化 — `tests/system/model_services_stub/server.py`

- 行为：将 `_next_call()` 改为在**同一把 `LOCK` 临界区**内读取 `ACTIVE_SCENARIO`
  并递增该场景计数，返回 `(scenario, ordinal)`。`/chat/completions` 处理由原先
  的“先读场景、释放锁、再经 `_next_call()` 重新加锁递增”改为单次
  `scenario, ordinal = _next_call()`，消除两次加锁之间的 `/__reset` 竞态。
- 保留：`/__reset` 仍在同一把 `LOCK` 内切换场景并清零计数；success、repair、
  timeout、failure 的响应合同（状态码、usage、阻塞/失败语义）完全不变；
  `/embeddings` 与 `/__calls/` 不受影响。

### Fix 3：Tutor repair 必须产生可用回答 — `tests/system/test_tutor_vertical.py`

- 行为：在 `test_tutor_invalid_answer_uses_bounded_repair` 中，于
  `assert turn["status"] == "succeeded"` 之后增加 `assert turn["answer_blocks"], turn`，
  与 success 路径断言同形。证明 repair 第三次调用确实产生了非空可用回答，
  而不是停留在第二次的空 `blocks`。
- 保留：精确 Provider Call phase 序列
  `["plan", "answer", "repair"]`、ordinal `[0, 1, 2]`、全部 `succeeded` 的断言不变。

### Fix 4：四链 provider failure 匹配稳定错误 — `apps/api/tests/test_four_chain_orchestration_postgres.py`

- 行为：将 `test_course_generation_provider_failure_orchestration` 中的裸
  `pytest.raises(ValueError)` 改为
  `pytest.raises(ValueError, match="generation_provider_unavailable")`。
- 事实依据（只读核对，未改产品代码）：`course_generation.call_provider()`
  对 `httpx.HTTPError`（`TimeoutException` 是其子类）统一 `raise
  ValueError("generation_provider_unavailable") from exc`，故
  `execute_generation()` 在 plan 阶段 provider timeout 时抛出该稳定错误码。
- 一致性：与本文件 RAG timeout 测试（`match="generation_provider_unavailable"`）
  以及 recorder 测试 `test_record_provider_call_empty_choices_course` 完全一致，
  与既有 focused tests / Spec 无冲突。
- 未修改产品错误行为；未改动该测试其余断言（mock call_count == 1、1 条
  `timed_out`/`provider_timeout`、phase `plan`、ordinal 0、owner 持久）。

### Fix 5：未来价格快照不依赖固定日历日期 — `apps/api/tests/test_provider_call_recorder.py`

- 行为：`test_price_snapshot_excludes_future` 中硬编码的
  `datetime(2027, 1, 1, tzinfo=timezone.utc)` 改为
  `datetime.now(timezone.utc) + timedelta(days=365)`，并在模块级
  `from datetime import ...` 增加 `timedelta`（模块级正常 import，未在函数内临时
  import）。
- 证明力不变：快照仍稳固落在未来，recorder 选择 `effective_at <= now` 的快照时
  不会绑定它，`provider_rate_snapshot_id is None` 断言继续成立。注释同步更新为
  “now + 365 days”，不再引用固定年份。

### Fix 6：Playwright 失败诊断与 dialog Promise — `apps/web/e2e/app-shell.spec.ts`

- 行为 1：`courseResponse.ok()` 断言升级为与 Reader 断言同级诊断，失败消息含
  HTTP status 与响应正文：
  `` `course request failed: ${courseResponse.status()} ${await courseResponse.text()}` ``。
- 行为 2：dialog handler 改为 async 回调并 `await dialog.accept()`：
  `page.once("dialog", async (dialog) => { await dialog.accept(); });`。
- 保留：Tutor 回答可见、`succeeded` 终态、`运行记录` tab 的 Tutor Run 断言
  全部不降级；未新增固定 sleep，仍以 `waitForResponse` / `toBeVisible` 等可观察
  状态等待真实响应。

## 2. 实际运行的命令及结果

### 2.1 窄检查（Fix 4 + Fix 5，覆盖 §6 第一组）

仓库根目录存在 `.venv`（Python 3.12.13，已含 `learn_platform_api` 全部依赖，
`psycopg 3.3.4`），且本地 Postgres 在 `127.0.0.1:55432` 可达（TCP OPEN）。
`test_provider_call_recorder.py` 走 `db_session` fixture（SQLite），`test_four_chain_orchestration_postgres.py`
硬编码 `localhost:55432`。按任务包 §6 注释“使用此前已经通过的、与本机 Docker/Postgres
相匹配的既有命令”，采用此前 handback 记录的 `.venv` 直跑命令（未改产品代码绕过环境差异）：

```bash
PYTHONPATH=apps/api ./.venv/Scripts/python.exe -m pytest -q \
  apps/api/tests/test_provider_call_recorder.py \
  apps/api/tests/test_four_chain_orchestration_postgres.py
```

**结果：73 passed in 142.49s**（recorder 62 + four-chain 11）。
覆盖 Fix 4（`test_course_generation_provider_failure_orchestration` 含新 `match` 通过）
与 Fix 5（`test_price_snapshot_excludes_future` 通过）。

### 2.2 受控 Tutor 系统测试（Fix 2 + Fix 3，§6）

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\system-test.ps1
```

栈自带 Postgres/Redis/Qdrant/API/worker/model-services stub/system-test-runner
（镜像已缓存，`--build` 增量）。**结果：退出码 0；`3 passed in 6.88s`**：

- `test_tutor_http_queue_worker_postgres_provider_call_path`（success）PASSED
- `test_tutor_invalid_answer_uses_bounded_repair`（repair，含新增 `answer_blocks` 断言）PASSED
- `test_tutor_timeout_is_recorded_and_enters_retry_wait`（timeout）PASSED

覆盖 Fix 2（stub 原子化未破坏 success/repair/timeout）与 Fix 3（repair 非空回答断言成立）。

### 2.3 Playwright 浏览器测试（Fix 6，§6）

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\browser-test.ps1
```

宿主 Playwright 1.62.0，已缓存 `chromium-1234`，系统 Chrome 可用作
`PLAYWRIGHT_CHANNEL=chrome`。**结果：退出码 0；`1 passed (3.9s)`**：

- `[chromium] › e2e\app-shell.spec.ts › Tutor flow reaches an answer and its run record` PASSED

真实 Tutor 用户流程跑通并看到成功运行记录，覆盖 Fix 6（诊断消息 + async
`dialog.accept()` 未破坏流程）。

### 2.4 Web lint / build（§6）

```bash
cd apps/web && npm.cmd run lint && npm.cmd run build
```

- **lint：0 errors**（7 个既有 warning，均在 `PracticePanel.tsx` /
  `QualityCostPanel.tsx`，与本任务文件无关）。
- **build：`✓ built in 7.62s`**（仅一条既有 chunk-size 提示，非错误）。

### 2.5 git diff --check（§6）

```bash
git diff --check
```

**结果：无错误（DIFF_CHECK_CLEAN）。** 注：`git diff --check` 只检查已跟踪改动；
本任务新增/改动的未跟踪文件（`scripts/browser-test.sh`、`tests/system/**`、
`apps/web/e2e/app-shell.spec.ts`、`apps/api/tests/test_four_chain_orchestration_postgres.py`）
不在其扫描范围。已跟踪文件 `apps/api/tests/test_provider_call_recorder.py` 通过检查。

### 2.6 Compose 配置预检

```bash
docker compose -f docker-compose.yml -f compose.system-test.yml config -q
```

**结果：退出码 0（配置有效）。**

## 3. 未运行项及具体原因

- **未对 `scripts/browser-test.sh` 单独端到端验证**：任务包 §6 的浏览器 Gate
  运行的是 `browser-test.ps1`（PowerShell 变体，本身用 `Push-Location`/`Pop-Location`
  处理工作目录，已正确并通过 §2.3）。`.sh`（bash 变体）的修正按 Fix 1 要求完成，
  通过代码审查确认子 shell 包裹后父目录不变、trap 与 `set -e` 退出传播保留；
  未在 Linux 容器内单独执行 bash 版（当前为 Windows 主机环境，本机 Gate 已用 .ps1）。
- **未运行 Docker 窄检查（`docker build --target test ...` + `docker run --network host ...`）**：
  本机 `.\.venv` 已含 API 全部依赖且本地 Postgres 55432 可达，直接复用此前已通过的
  `.venv` 命令（§2.1）即可覆盖同一批测试，与任务包 §6“使用此前已经通过的既有命令”
  一致；未为绕过环境差异修改任何产品代码。该 Docker 命令本身未再重复执行。
- **未运行任何 OCR**：按任务包与 Playbook，本修正包不运行真实 OCR。
- **其余未列命令**：均按要求未执行（见 §4/§5）。

## 4. 产品代码零修改证明

- 本任务**仅**修改任务包 §3 允许的 6 个文件：
  - `scripts/browser-test.sh`（Fix 1）
  - `tests/system/model_services_stub/server.py`（Fix 2）
  - `tests/system/test_tutor_vertical.py`（Fix 3）
  - `apps/api/tests/test_four_chain_orchestration_postgres.py`（Fix 4）
  - `apps/api/tests/test_provider_call_recorder.py`（Fix 5）
  - `apps/web/e2e/app-shell.spec.ts`（Fix 6）
- 未修改 `apps/api/learn_platform_api/**` 任何文件。`git status` 中
  `apps/api/learn_platform_api/services/{answers,course_generation,practice_generation,provider_call_recorder,tutor_generation}.py`
  的改动是本任务**开始前已存在**的 GLM Slice 2A dirty 文件，本任务未对其做任何
  编辑（仅只读核对 `course_generation.call_provider()` 以确认 Fix 4 稳定错误码）。
- `apps/api/tests/test_provider_call_recorder.py` 的 `git diff`（相对 HEAD）
  包含大量既有 GLM 改动（ADR 004 `_sf`/`_session_factory`/commit、`import hashlib`、
  rollback 持久化测试等）；**本任务对该文件的改动仅两处**：模块级 datetime import
  增加 `timedelta`，以及 `test_price_snapshot_excludes_future` 用
  `datetime.now(timezone.utc) + timedelta(days=365)` 替换硬编码 `2027-01-01`。
- 未修改 migration、ORM schema、Web 产品源码、Compose、CI、Provider Call 语义或
  业务 orchestration。

## 5. 未 commit、未 push、未运行 OCR、未进入 Slice 2B

- ✅ 未 commit，未 push。
- ✅ 未运行 OCR（真实 review / scan 均未触发）。
- ✅ 未进入 Slice 2B；未新增 provider failure 系统场景（属 Slice 2B 候选输入）。
- ✅ 未安装依赖、未调用真实 provider。
- ✅ 未读取或修改 `.tmp/`、`artifacts/`。
- ✅ 未处理任务包 §5“明确不采纳”的 OCR 评论（未降级 actions 版本、未动
  `scripts/system-test.sh`、未引入测试凭据 Secrets、未改业务 commit 合同、未重构
  `_test_session_factory`/ordinal/业务 session fixture、未清理无关 import/历史测试、
  未增依赖）。
- ✅ 未回滚或覆盖既有 dirty files（`git status --short --branch` 与开始时一致）。

## 6. 已知风险或合同冲突

无新增风险。六项修复均为测试/脚本/stub/Playwright 层面的窄修正；Fix 4 的
`match` 已对照产品实际抛出的稳定错误码确认一致，无合同冲突。若后续产品
`call_provider()` 错误码变更，该 `match` 应同步更新。
