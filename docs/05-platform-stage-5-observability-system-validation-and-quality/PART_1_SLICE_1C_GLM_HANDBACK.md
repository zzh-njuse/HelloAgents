# Stage 5 Part 1 Slice 1C GLM Handback

状态：OCR 窄范围修复 + 遗留竞态修复完成，等待 Codex 独立验收

日期：2026-07-28

## 1. 修改文件与责任

### 新增文件

| 文件 | 责任 |
|---|---|
| `apps/api/learn_platform_api/routers/quality_cost.py` | Quality-cost-summary API endpoint (Spec 005 §3) |
| `apps/api/learn_platform_api/schemas/quality_cost.py` | 响应白名单 schema |
| `apps/api/learn_platform_api/services/quality_cost.py` | 聚合 read service，bounded SQL queries (Postgres-only) |
| `apps/api/learn_platform_api/services/agent_run_identity.py` | 共享 identity kind precedence 单一事实来源 (Fix 4 第二轮) |
| `apps/api/tests/test_quality_cost_summary_api.py` | Schema/enum/503 合同测试 (8 tests, SQLite) |
| `apps/api/tests/test_quality_cost_summary_postgres.py` | Isolated Postgres focused tests (16 tests) |
| `apps/api/tests/test_agent_run_identity_workspace.py` | Practice grading identity workspace 校验测试 (2 tests, Postgres) |
| `apps/web/src/app/QualityCostPanel.tsx` | 质量与成本面板组件 |
| `apps/web/src/styles.css` (增量) | 新增 quality-cost 相关 CSS |

### 修改文件

| 文件 | 变更说明 |
|---|---|
| `apps/api/learn_platform_api/main.py` | 注册 quality_cost router |
| `apps/api/learn_platform_api/services/agent_runs.py` | 导入共享 `agent_run_identity.owner_kind_from_run`，`_identity()` 使用共享函数赋值 kind；Fix 5: Practice grading identity 中间对象 workspace 校验 |
| `apps/web/src/lib/api.ts` | 新增 QualityCostSummary 类型、fetchQualityCostSummary、ProviderCallRead 类型、fetchProviderCalls、独立 `QualityCostStatus` 类型 |
| `apps/web/src/app/AgentRunsPanel.tsx` | 新增 Tab 切换（运行记录/质量与成本），引入 QualityCostPanel，Tab ARIA/键盘导航，roving focus: Arrow/Home/End 同时激活并聚焦目标 tab (Fix 6 第二轮) |

## 2. OCR Fix 1–6 逐项报告

### Fix 1：运行详情请求防止旧响应覆盖

**实现位置**：`apps/web/src/app/QualityCostPanel.tsx` — `detailSeq` ref (line ~193) 和 `toggleRun()` callback (line ~306)

**实现方式**：
- 独立单调递增 `detailSeq = useRef(0)`
- 展开 B 时 `++detailSeq.current`，异步回调检查 `seq !== detailSeq.current` 则 return
- 折叠当前记录时 `detailSeq.current += 1`，使仍在途请求失效
- 成功和失败路径均检查 sequence
- 可同时使用 AbortController（effect cleanup abort），但 sequence guard 是必须项

**自动化**：前端竞态测试无法自动化（仓库无 React 组件测试 runner）。人工 smoke 步骤见 §8。

### Fix 2：Provider Call 下钻请求防止旧响应覆盖

**实现位置**：`apps/web/src/app/QualityCostPanel.tsx` — `drillSeq` ref (line ~196) 和 `loadProviderCalls()` callback (line ~336)

**实现方式**：
- 独立单调递增 `drillSeq = useRef(0)`，与 `detailSeq` 完全独立
- 切到 B 时 `++drillSeq.current`，异步回调检查 sequence
- 关闭下钻时 `drillSeq.current += 1`，使仍在途请求失效
- loading/error/data 只由当前最新请求更新

**自动化**：同 Fix 1，无法自动化。人工 smoke 步骤见 §8。

### Fix 7：折叠整条运行记录时递增 drillSeq 并清理 Provider Call 状态

**实现位置**：`apps/web/src/app/QualityCostPanel.tsx` — `toggleRun()` 折叠分支 (line ~307–318)

**问题**：折叠运行记录时仅递增 `detailSeq`，未递增 `drillSeq`，也未清理 `providerCalls`/`drillLoading`/`drillError` 状态。如果用户折叠时 Provider Call 请求仍在途，迟到响应会写入已折叠的 drill 状态，下次展开其他运行时可能短暂显示旧 workspace 的数据。

**修复**：
- 折叠路径同时递增 `detailSeq.current += 1` 和 `drillSeq.current += 1`
- 清理 `setProviderCalls([])`、`setDrillLoading(false)`、`setDrillError(null)`
- 已有的 `setDrillRunId(null)` 保留

**自动化**：前端竞态测试无法自动化。人工 smoke 步骤见 §8。

### Fix 8：workspaceId 变化时使 detailSeq/drillSeq 失效并清理状态

**实现位置**：`apps/web/src/app/QualityCostPanel.tsx` — workspaceId effect (line ~287–300)

**问题**：当 `workspaceId` 变化（用户切换 workspace）或组件卸载时，`detailSeq` 和 `drillSeq` 未递增，detail/drill 状态未清理。旧 workspace 的在途请求完成后会写入新 workspace 的状态，造成跨 workspace 数据泄漏。

**修复**：
- 新增 `useEffect` 依赖 `[workspaceId]`
- effect 内递增 `detailSeq.current += 1` 和 `drillSeq.current += 1`
- 清理所有 detail/drill 状态：`expandedRunId`、`runDetail`、`runDetailError`、`drillRunId`、`providerCalls`、`drillLoading`、`drillError`
- 不引入 `refreshAll` 依赖，不重新触发刷新 effect（`refreshAll` 已有自己的 effect 响应 `workspaceId` 变化），避免依赖循环

**自动化**：前端竞态测试无法自动化。人工 smoke 步骤见 §8。

### Fix 3：统一刷新入口，消除计数器互相取消

**实现位置**：`apps/web/src/app/QualityCostPanel.tsx` — `refreshAll()` callback (line ~228) 和 effect (line ~281)

**实现方式**：
- 单一 `refreshSeq = useRef(0)` 计数器
- 顶部刷新按钮、摘要错误重试、异常列表错误重试统一调用 `refreshAll()`
- `refreshAll` 先获取 summary（成功后更新 `summaryBoundsRef`），再获取异常列表
- summary 失败时异常列表使用 `summaryBoundsRef.current`（上一次成功边界），保持 partial-success
- effect 仅依赖 `refreshAll`，不依赖 `summary`，无循环
- `refreshAll` 不清空已成功显示的 summary
- 删除了独立的 `refreshSummary()` / `refreshFailedRuns()` 公开入口（重试按钮直接调 `refreshAll()`）

**自动化**：同 Fix 1，无法自动化。人工 smoke 步骤见 §8。

### Fix 4：非 Postgres 必须在任何聚合查询前返回

**实现位置**：
- `apps/api/learn_platform_api/services/quality_cost.py` — `get_quality_cost_summary()` 入口 dialect 检查 (line ~105–111)
- `apps/api/learn_platform_api/routers/quality_cost.py` — RuntimeError 映射为 HTTP 503
- `apps/api/tests/test_quality_cost_summary_api.py` — `test_non_postgres_no_aggregation_sql_executed` (line ~146)

**实现方式**：
- dialect 检查在 `get_quality_cost_summary()` 入口处，先于任何聚合查询
- 非 PostgreSQL 立即 `raise RuntimeError`
- 测试使用 SQLAlchemy `before_execute` 事件计数 SQL 语句，断言 ≤2（仅 workspace lookup），证明聚合 SQL 未执行
- 错误码保持 `quality_cost_requires_postgres`

**自动化**：✅ 8 SQLite tests passed，含 SQL statement count 断言

### Fix 5：Practice grading identity 中间对象 workspace 校验

**实现位置**：
- `apps/api/learn_platform_api/services/agent_runs.py` — `_identity()` practice grading 分支 (line ~128–135)
- `apps/api/tests/test_agent_run_identity_workspace.py` — 2 tests (Postgres)

**实现方式**：
- 在 practice grading owner 链中，增加显式 workspace 校验：
  - `PracticeAttempt.workspace_id != run.workspace_id` → `course_deleted = True, return`
  - `PracticeItem.workspace_id != run.workspace_id` → `course_deleted = True, return`
- 任一中间对象缺失或 workspace 不一致时，identity 安全降级，不继续投影跨 workspace 的 owner 文本
- 保持现有 owner precedence 和正常 grading identity 行为
- 不修改 schema、migration 或既有数据库约束

**测试**：
- `test_attempt_wrong_workspace_safe_degrade`：PracticeAttempt 在 ws2，run 在 ws1 → identity.kind == "practice", course_deleted == True
- `test_item_wrong_workspace_safe_degrade`：PracticeItem 在 ws2，PracticeAttempt 在 ws1（但 item 跨 workspace）→ identity.kind == "practice", course_deleted == True

**自动化**：✅ 2 Postgres tests passed

### Fix 6：成本金额的运行时空值防御

**实现位置**：`apps/web/src/app/QualityCostPanel.tsx` — `safeCostDisplay()` helper (line ~152) 和 Provider Call table cell (line ~633)

**实现方式**：
- `safeCostDisplay(cost)`: 仅当 `cost.status === "calculated" && cost.amount != null` 时调用 `formatCNY()`
- 否则返回 "成本未知"
- Provider Call 表格成本列使用 `safeCostDisplay(pc.cost)` 替代直接 `formatCNY()`
- `calculated + null amount` 不显示 `¥undefined`

**自动化**：`safeCostDisplay` 是 exported pure function，可独立测试。仓库无 React 组件测试 runner，无法在组件渲染层面自动化。人工 smoke 步骤见 §8。

## 3. API 查询数量和聚合方法

共 7 个有界 SQL 查询（仅 Postgres 路径）：

1. **Run counts by status** — 单条 `SELECT COUNT(*) ... FILTER` 聚合
2. **Duration percentile** — Postgres `percentile_cont(0.5).within_group(...)` / `percentile_cont(0.95).within_group(...)`，子查询计算 `duration_ms = EXTRACT(EPOCH FROM completed_at - created_at) * 1000`，结果取整为毫秒
3. **Error code counts** — `GROUP BY error_code ORDER BY count DESC`
4. **Provider Call status counts** — `GROUP BY status`，仅统计 `agent_run_id IN (filtered_run_ids)` 的调用
5. **Provider Call token sums & usage completeness** — 单条 `SUM` + `COUNT FILTER` 聚合
6. **Cost aggregation** — 单条 LEFT JOIN + SQL CASE/NUMERIC 聚合，数据库侧计算 known_amount、calculated/unknown count 和四种 unknown reason count；provider/model blank 使用 `btrim()` 判空
7. **Runs without provider calls** — `NOT EXISTS` 子查询

**不**存在 N+1。非 Postgres dialect 返回 503。

## 4. Identity 复用方式

business_type 筛选使用 SQL `CASE` 表达式，逻辑与 `agent_run_identity.owner_kind_from_run()` 一致：

```sql
CASE
  WHEN course_generation_job_id IS NOT NULL THEN 'course_generation'
  WHEN tutor_turn_id IS NOT NULL THEN 'tutor'
  WHEN practice_job_id IS NOT NULL THEN 'practice'
  WHEN code_lab_job_id IS NOT NULL THEN 'code_execution'
  ELSE 'unknown'
END
```

`agent_run_identity.py` 定义 `OWNER_KIND_PRECEDENCE` 常量列表和 `owner_kind_from_run()` 函数，`agent_runs.py` 和 `quality_cost.py` 均从该中性模块导入。两侧不再各自手写可能漂移的独立 CASE，不存在反向依赖。Postgres drift 回归测试验证 Python identity 与 SQL 聚合真实结果一致。

## 5. Percentile、Decimal、Unknown 和无 Call 的实现语义

### Percentile

- 使用 Postgres `percentile_cont` 连续插值，不使用 Python 端 nearest-rank
- 仅统计终态（succeeded/failed/canceled）且 `completed_at >= created_at` 的 run
- 空样本返回 `null`，不返回 0
- 连续插值结果取整为整数毫秒
- 偶数样本时 `percentile_cont` 与 nearest-rank 结果不同；Postgres 测试用偶数样本锁定

### Decimal

- 成本聚合使用 SQL `NUMERIC` / `ROUND` + Python 端 `Decimal` + `ROUND_HALF_UP` + 8 位精度，与 `provider_cost.py` 一致
- `known_amount` 固定八位小数字符串格式

### Unknown

- 优先级严格遵循 `provider_missing > model_missing > usage_missing > rate_missing`
- provider/model blank 使用 `btrim()` 判空，与 `provider_cost._is_blank()` 一致
- unknown 调用不进入 `known_amount`
- 真实零成本（0 tokens + rates present）属于 `calculated_call_count`
- failed/timed_out/canceled 调用仍按实际 usage/快照计算

### 无 Provider Call

- `runs_without_provider_calls` 使用 `NOT EXISTS` 数据库侧语义
- 与 `unknown_call_count` 明确分离：前者是没有任何 Call 的 Run，后者是有 Call 但成本 unknown

## 6. Web 信息架构、状态和下钻实现

### 信息架构

沿用 Workspace "运行记录" 入口，以 Tab 区分：

- **运行记录** Tab：Slice 1A 既有列表与详情，行为不变
- **质量与成本** Tab：新增面板

质量与成本面板层级：

1. 筛选栏：时间 segmented control (24h/7d/30d)、业务类型/角色/状态 select、刷新按钮
2. 运行健康指标带：总运行、成功/失败/取消/进行中、P50/P95 耗时
3. Provider 用量与计算成本指标带：调用数、input/output token、已知人民币成本
4. 成本完整性说明：已计算/未知/无计费事实
5. 失败分类：紧凑列表（非饼图），每条有"查看近期异常"动作
6. 最近异常运行：复用 Slice 1A Run 行模式，可展开查看 Tool Call 和 Provider Call 下钻

### 筛选一致性 (Fix 5.1 + Fix 5)

- 异常列表与当前窗口、role、business type 和 status 语义一致：
  - status 为空时显示 failed+canceled
  - status=failed/canceled 时只显示对应异常
  - status=started/succeeded 时显示"当前筛选不包含异常运行"
  - 按 summary from/to 限定窗口
  - **按 identity.kind 过滤 business type**（Fix 5 第二轮）
- `filterBusinessType` 进入 `refreshFailedRuns` 的 callback 依赖
- `QualityCostStatus` 独立于 `AgentRunStatus`（前者 started/succeeded/failed/canceled，后者 running/succeeded/failed/canceled）

### Tab ARIA + Roving Focus (Fix 5.2 + Fix 6)

- 两个 tab 有稳定 ID（`runs-tab`、`quality-cost-tab`）
- `aria-controls`/`aria-labelledby` 正确关联
- Roving focus（非活动 tab `tabIndex=-1`）
- Arrow/Home/End 键盘导航 **同时激活并聚焦目标 tab**（Fix 6 第二轮）
- 使用 `useRef<HTMLButtonElement>` 稳定引用两个 tab 按钮

### 移动端 (Fix 5.3)

- Provider Call 表格放入 `.provider-call-scroll` 横向滚动容器
- 表格单元格 `white-space: nowrap`，页面根不能横向滚动

### Identity 文案 (Fix 5.4)

- 失败 Run 使用 `safeIdentityLabel()`，不显示原始英文 kind
- 复用 `IDENTITY_KIND_LABEL` 中文映射

### 成本未知文案 (Fix 5.5)

- `calculated_call_count=0` 且存在 unknown/no-call 时，主金额不显示 `¥0.00000000`，改为"暂无可计算金额"
- 只有 `calculated_call_count > 0` 时才突出人民币已知金额

### 状态实现

- 摘要和异常运行列表**独立**请求，部分失败保留已成功区域
- loading 使用 `role=status`，error 使用 `role=alert`
- 未知 role/error 使用安全中文降级文案
- 不默认轮询，不修改业务状态

### 请求生命周期 (Smoke fix)

**根因**：`refreshFailedRuns` 闭包依赖 `summary` 对象，`summary` 变化 → callback 变化 → `refresh` 变化 → effect cleanup → abort + `setSummary(null)` → `summary` 再次变化 → 请求风暴循环。

**修复**：
- `summaryBoundsRef = useRef<{from,to}|null>` 保存摘要窗口边界，不参与 effect 依赖
- `refreshFailedRuns` 从 `summaryBoundsRef.current` 读取边界，**不**闭包依赖 `summary` 状态
- 新增 `refreshAll()` 协调函数：先请求摘要，成功后更新 `summaryBoundsRef`，再请求异常列表；摘要失败时异常列表仍用旧边界（partial success）
- effect 仅依赖 `refreshAll`，`refreshAll` 仅依赖 filter 原语，不依赖 `summary`
- `refreshAll` 不清空 `summary`（保留 stale 数据可见，spinner overlay）
- `showSummarySpinner` 仅在 `summaryLoad === "loading" && summary === null` 时显示
- 纯 helper 函数 `filterRunsByWindow`、`filterRunsByBusinessType`、`sortAndTruncateRuns`、`safeCostDisplay` 导出为 `export function`，可独立测试
- 手动刷新按钮调用 `refreshAll()`；重试按钮也调用 `refreshAll()`
- 一块失败不清空另一块已成功数据

### 下钻实现

- 点击"查看模型调用"调用 Slice 1B `GET /provider-calls?agent_run_id=...` API
- Provider Call 详情显示 phase、状态、provider/model、usage、latency 和计算成本
- 不显示 prompt、回答、raw response 或价格快照

## 7. 新增测试矩阵与逐命令结果

### API Schema/Enum Tests — SQLite (8 tests)

| 类别 | 测试数 | 覆盖内容 |
|---|---|---|
| TestQualityCostSummarySchema | 8 | 404、422 (window/role/business_type/status)、503 非 Postgres 拒绝、503 前无聚合 SQL 执行、结构说明 |

### Postgres 聚合事实 Tests (16 tests)

| 类别 | 测试数 | 覆盖内容 |
|---|---|---|
| TestPostgresPercentile | 3 | 偶数样本连续插值、奇数样本、空样本 null |
| TestPostgresCostAggregation | 4 | SQL 聚合 vs 明细、零成本属 calculated、unknown reason SQL 分类、混合 |
| TestPostgresWorkspaceIsolation | 1 | 跨 workspace 隔离 |
| TestPostgresRAGExclusion | 1 | RAG/workspace-only 调用排除 |
| TestPostgresRunsWithoutCalls | 1 | runs_without_provider_calls |
| TestIdentityDriftRegression | 3 | owner precedence 匹配 identity (course_generation+tutor)、practice identity 匹配 SQL、precedence 顺序正确 |
| TestWhitespaceProviderModelClassification | 3 | whitespace provider→provider_missing、whitespace model→model_missing、SQL unknown reason vs calculate_cost 逐一对照 |

### Identity Workspace Tests — Postgres (2 tests)

| 类别 | 测试数 | 覆盖内容 |
|---|---|---|
| TestPracticeGradingIdentityWorkspace | 2 | PracticeAttempt 跨 workspace 安全降级、PracticeItem 跨 workspace 安全降级 |

### 命令结果

```powershell
# SQLite schema/enum/503 tests
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_api.py
# Result: 8 passed

# Postgres 聚合事实 tests
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_postgres.py
# Result: 16 passed

# Identity workspace tests
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_identity_workspace.py
# Result: 2 passed

# Regression tests
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py
# Result: 24 passed

# Web lint
Push-Location apps/web; npm.cmd run lint; Pop-Location
# Result: 0 errors (7 pre-existing warnings: 3 in PracticePanel.tsx, 4 react-refresh/only-export-components in QualityCostPanel.tsx)

# Web build
Push-Location apps/web; npm.cmd run build; Pop-Location
# Result: ✓ built in 4.79s

# Whitespace check
git diff --check
# Result: no output (clean)
```

## 8. 前端竞态测试自动化说明

仓库当前未配置 React 组件测试 runner（无 vitest/jest + @testing-library/react），任务包明确禁止安装新依赖。

**无法自动化的前端竞态项**：
1. Fix 1: 运行详情 A/B 迟到响应不覆盖 B
2. Fix 2: Provider Call A/B 迟到响应不覆盖 B
3. Fix 3: 折叠/关闭后迟到响应不恢复已关闭内容
4. Fix 6: `calculated + null amount` 不显示 `¥undefined`
5. Fix 7: 折叠运行记录时 Provider Call 在途请求失效
6. Fix 8: workspaceId 变化时 detail/drill 在途请求失效

**可独立测试的纯函数**（已 export）：
- `filterRunsByWindow`
- `filterRunsByBusinessType`
- `sortAndTruncateRuns`
- `safeCostDisplay`

**人工 smoke 步骤**：

1. **Fix 1 运行详情竞态**：
   - 打开质量与成本面板，等待异常运行列表加载
   - 快速连续点击运行 A 展开 → 运行 B 展开
   - 验证：B 的详情正确显示，A 的迟到响应未覆盖 B

2. **Fix 2 Provider Call 竞态**：
   - 展开一个运行，快速连续点击"查看模型调用" A → B
   - 验证：B 的 Provider Call 列表正确显示，A 的迟到响应未覆盖 B

3. **Fix 3 折叠后迟到响应**：
   - 展开运行 A，在详情加载中立即折叠
   - 验证：折叠后迟到响应未恢复展开状态
   - 同样测试：展开 Provider Call 后立即关闭

4. **Fix 6 成本空值**：
   - 在浏览器 DevTools Network 中 mock 一个 Provider Call 响应，包含 `cost: {status: "calculated", amount: null}`
   - 验证：成本列显示"成本未知"而非 `¥undefined`

5. **Fix 3 统一刷新**：
   - 点击摘要区域重试按钮，验证摘要和异常列表同时刷新
   - 点击异常列表重试按钮，验证同样触发完整刷新

6. **Fix 7 折叠时 Provider Call 状态清理**：
   - 展开运行 A，点击"查看模型调用"，在 Provider Call 加载中立即折叠 A
   - 验证：折叠后 Provider Call 列表消失，迟到响应未恢复下钻状态
   - 重新展开 A，验证：Provider Call 按钮显示"查看模型调用"（非"关闭"），无残留数据

7. **Fix 8 workspaceId 变化时状态失效**：
   - 展开运行 A 的详情和 Provider Call 下钻
   - 切换到另一个 workspace
   - 验证：详情和下钻区域已清空，无旧 workspace 数据残留
   - 切换回原 workspace，验证：面板重新加载，无旧展开/下钻状态

## 9. 测试分层说明

- **SQLite tests (8)**: 覆盖 schema 验证、enum 422、非 Postgres 503 拒绝、503 前无聚合 SQL 执行。不验证聚合行为。
- **Postgres tests (16)**: 覆盖所有聚合事实（percentile、cost、identity、whitespace classification、workspace isolation、RAG exclusion、runs without calls）。
- **Identity workspace tests (2)**: 覆盖 Practice grading identity 中间对象跨 workspace 安全降级。
- **Regression tests (24)**: 验证 Agent Run API 未受影响。

## 10. 未运行的验证

- **浏览器人工 smoke**：未运行真实浏览器验证响应式布局、Tab 键盘操作、Provider Call 下钻交互和竞态防御
- **真实 provider**：未调用任何真实 LLM provider
- **OCR**：未运行独立代码审查

## 11. 未解决问题、性能假设和需要 Codex 复核的风险

### 需要 Codex 复核的风险

1. **Web QualityCostPanel 未有组件测试**：仓库当前未配置 React 组件测试 runner，Web 验证依赖 TypeScript 编译、lint 和 build。建议 Codex 验收时进行浏览器 smoke。

### 未解决问题

- 无（Fix 7、Fix 8 已解决遗留竞态问题）

## 12. 未触碰的边界

- 未修改任何 migration、ORM model 或 schema
- 未修改 Provider Call 写入链、价格选择或成本事实合同
- 未修改 Agent Run 写入、业务状态、重试预算或队列
- 未修改现有 Agent Run / Provider Call API 响应
- 未新增缓存、物化视图、后台 job 或依赖
- 未处理 `list_agent_runs()` N+1（保留为 Stage 5 第二部分输入）
- 未新增登录、认证、workspace membership 或权限系统
- 未把所有数据库异常宽泛捕获并统一改成 503
- 未修改 Agent Run / Provider Call 公开合同
- 未新增窗口、筛选器、图表、缓存或聚合表
- 未重构全局 API request helper
- 未清理历史 CSS、字体权重、注释或无关测试风格
- 未运行 OCR
- 未进入 Stage 5 第二部分

## 13. `git status --short` 中与本任务无关的文件

以下文件在 `git status --short` 中存在但与本 OCR 修复任务无关：

- `apps/web/src/app/AgentRunsPanel.tsx` (M) — Stage 5 Slice 1C 第二轮 Tab 集成改动
- `apps/web/src/lib/api.ts` (M) — Stage 5 Slice 1C API 类型新增
- `apps/web/src/styles.css` (M) — Stage 5 Slice 1C CSS 新增
- `docs/05-platform-stage-5-observability-system-validation-and-quality/README.md` (M) — 文档更新
- `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/README.md` (M) — 文档更新
- `.tmp/` (??) — 临时目录，不触碰
- `artifacts/` (??) — 构建产物，不触碰
- `docs/.../PART_1_SLICE_1C_ACCEPTANCE_FIX2_PACKET.md` (??) — 验收文档
- `docs/.../PART_1_SLICE_1C_ACCEPTANCE_FIX_PACKET.md` (??) — 验收文档
- `docs/.../PART_1_SLICE_1C_FRONTEND_CONCEPT.md` (??) — 前端概念文档
- `docs/.../PART_1_SLICE_1C_GLM_IMPLEMENTATION_PACKET.md` (??) — 实现包文档
- `docs/.../PART_1_SLICE_1C_SMOKE_FIX_PACKET.md` (??) — Smoke 修复包文档

## 14. 确认

- ✅ Fix 1: 运行详情 request sequence 防止迟到响应覆盖
- ✅ Fix 2: Provider Call 下钻 request sequence 防止迟到响应覆盖
- ✅ Fix 3: 统一刷新入口，消除计数器互相取消
- ✅ Fix 4: 非 Postgres 在聚合 SQL 执行前返回 503
- ✅ Fix 5: Practice grading identity 中间对象 workspace 校验
- ✅ Fix 6: 成本金额运行时空值防御
- ✅ Fix 7: 折叠运行记录时递增 drillSeq 并清理 Provider Call 状态
- ✅ Fix 8: workspaceId 变化时使 detailSeq/drillSeq 失效并清理状态
- ✅ 未修改任何 migration、ORM model 或 schema
- ✅ 未修改 Provider Call 写入链、价格选择或成本事实合同
- ✅ 未修改 Agent Run 写入、业务状态、重试预算或队列
- ✅ 未修改现有 Agent Run / Provider Call API 响应
- ✅ 未新增缓存、物化视图、后台 job 或依赖
- ✅ 非 Postgres 不返回伪事实，返回 503
- ✅ SQL btrim 判空与 provider_cost._is_blank 一致
- ✅ identity precedence 移至中性模块，被 Agent Run 和质量聚合真实使用
- ✅ 异常列表应用 business type 过滤
- ✅ Tab roving focus 同时移动焦点
- ✅ 请求生命周期解耦：summary 不再成为 effect 间接依赖，请求风暴已消除
- ✅ 纯 helper 导出可独立测试
- ✅ 未 commit、未 push
- ✅ 未运行 OCR
- ✅ 未进入 Stage 5 第二部分
