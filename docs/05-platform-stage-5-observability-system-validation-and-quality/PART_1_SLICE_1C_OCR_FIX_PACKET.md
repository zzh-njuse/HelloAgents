# Stage 5 Part 1 Slice 1C OCR 修复任务包

## 1. 任务性质

这是 Slice 1C 独立 OCR 后的窄范围修复，不是功能扩展，也不是重新设计。

仅修复本文列出的六项问题。不要进入 Stage 5 第二部分，不要顺手重构现有运行记录、认证、全局 API 错误处理或 CSS。

## 2. 开始前

1. 阅读根 `AGENTS.md`。
2. 阅读：
   - `docs/AGENT_COLLABORATION_PLAYBOOK.md`
   - `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
   - `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/005-workspace-quality-cost-read-experience.md`
   - `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_SLICE_1C_GLM_HANDOFF.md`（若不存在，以当前实现包和 Handback 为准）
   - `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_SLICE_1C_GLM_HANDBACK.md`
3. 检查 `git status --short --branch`，保留所有未知改动。
4. 不读取、修改、删除或提交 `.tmp/`、`artifacts/`。

## 3. 修复范围

### Fix 1：运行详情请求防止旧响应覆盖

文件：

- `apps/web/src/app/QualityCostPanel.tsx`

为 `toggleRun()` 增加单调递增的 request sequence/ref。

要求：

- 用户先展开 A、再快速展开 B 时，A 的迟到响应不得写入 B 的展开区域。
- 折叠当前记录时必须使该记录仍在途的请求失效。
- workspace 变化、组件卸载或筛选刷新后，旧响应不得更新当前详情状态。
- 成功和失败路径都必须检查 request sequence。
- 可以同时使用 `AbortController`，但不能只依赖 abort；sequence guard 是必须项。

### Fix 2：Provider Call 下钻请求防止旧响应覆盖

文件：

- `apps/web/src/app/QualityCostPanel.tsx`

为 `loadProviderCalls()` 增加独立的 request sequence/ref。

要求：

- 从运行 A 快速切到运行 B 时，A 的 Provider Call 响应不得显示在 B 下方。
- 关闭下钻时必须使仍在途请求失效。
- loading、error、data 只能由当前最新请求更新。
- 不得与运行详情 request sequence 共用同一个 ref。

### Fix 3：统一刷新入口，消除计数器互相取消

文件：

- `apps/web/src/app/QualityCostPanel.tsx`

当前 `refreshSummary()`、`refreshFailedRuns()` 与 `refreshAll()` 共用请求计数器，独立重试可能使协调刷新提前返回。

要求：

- 顶部刷新、摘要错误重试、异常列表错误重试统一调用协调刷新入口。
- 删除不再需要的独立网络刷新函数，或将其变为不会产生第二套 request sequence 的轻量委托。
- 一次协调刷新仍须先获取 summary，以新的 `{from, to}` 过滤异常列表。
- summary 失败时允许异常列表使用上一次成功边界，保持既有 partial-success 行为。
- 保留 smoke 修复：effect 依赖不得重新引入 `summary -> callback -> effect` 循环。
- 不得在刷新开始时清空已经成功显示的 summary。

### Fix 4：非 Postgres 必须在任何聚合查询前返回

文件：

- `apps/api/learn_platform_api/services/quality_cost.py`
- `apps/api/tests/test_quality_cost_summary_api.py`

要求：

- 将 dialect 检查移动到 `get_quality_cost_summary()` 的入口处。
- 在构造或执行任何聚合查询前，对非 PostgreSQL 抛出当前稳定的 `RuntimeError`。
- router 继续映射为 HTTP 503，错误码保持：
  - `quality_cost_requires_postgres`
- 不添加 SQLite 伪聚合或 Python 全量加载降级。
- 增加测试证明 SQLite 503 路径没有执行聚合 SQL。可使用 SQLAlchemy statement 计数或等价的明确断言，不能只断言最终状态码。

### Fix 5：Practice grading identity 中间对象 workspace 校验

文件：

- `apps/api/learn_platform_api/services/agent_runs.py`
- 对应 focused API/identity 测试

在 Practice grading owner 链中，对以下中间对象增加显式 workspace 一致性校验：

- `PracticeAttempt.workspace_id == run.workspace_id`
- `PracticeItem.workspace_id == run.workspace_id`

要求：

- 任一中间对象缺失或 workspace 不一致时，identity 必须安全降级，不得继续投影跨 workspace 的 owner 文本。
- 保持现有 owner precedence 和正常 grading identity 行为。
- 添加真实 ORM 行为测试，至少覆盖 attempt 错 workspace 与 item 错 workspace。
- 不修改 schema、migration 或既有数据库约束。

### Fix 6：成本金额的运行时空值防御

文件：

- `apps/web/src/app/QualityCostPanel.tsx`

仅当：

- `pc.cost.status === "calculated"`；且
- `pc.cost.amount != null`

时调用 `formatCNY()`。

异常合同数据不得显示 `¥undefined`，统一显示现有“成本未知”文案。

## 4. 明确不做

- 不新增登录、认证、workspace membership 或权限系统。
- 不把所有数据库异常宽泛捕获并统一改成 503。
- 不修改 Agent Run / Provider Call 公开合同。
- 不处理既有 `list_agent_runs()` N+1；将其保留为 Stage 5 第二部分 CI/系统测试和性能优化输入。
- 不新增窗口、筛选器、图表、缓存或聚合表。
- 不重构全局 API request helper。
- 不清理历史 CSS、字体权重、注释或无关测试风格。
- 不修改 migration、ORM schema、provider recorder、价格快照或业务写入链。
- 不运行 OCR。

## 5. 测试要求

至少新增或调整以下自动化覆盖：

1. 运行详情 A/B 迟到响应不会覆盖 B。
2. Provider Call A/B 迟到响应不会覆盖 B。
3. 折叠详情或下钻后，迟到响应不会恢复已关闭内容。
4. 摘要重试和异常列表重试均走统一协调刷新。
5. 非 Postgres 在聚合 SQL 执行前返回 503。
6. PracticeAttempt 跨 workspace 时安全降级。
7. PracticeItem 跨 workspace 时安全降级。
8. `calculated + null amount` 不显示 `¥undefined`。

若仓库当前没有前端单元测试基础设施，不要安装新依赖。改为：

- 导出或抽取最小纯状态辅助函数进行现有可用测试；或
- 在 Handback 中明确说明无法自动化的前端竞态项，并提供可复现的人工 smoke 步骤。

## 6. 验证命令

使用仓库现有环境执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_api.py
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_postgres.py
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py
```

Web：

```powershell
Push-Location apps/web
npm.cmd run lint
npm.cmd run build
Pop-Location
```

最后：

```powershell
git diff --check
```

Postgres 测试只能使用现有隔离测试机制和 throwaway database，不得触碰开发数据库。

## 7. Handback 要求

更新：

- `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_SLICE_1C_GLM_HANDBACK.md`

必须逐项说明：

- Fix 1 至 Fix 6 的实际实现位置；
- 新增或调整的测试；
- 每条验证命令的真实结果；
- 前端竞态测试是否自动化；若没有，说明原因和人工 smoke 步骤；
- 未触碰的边界；
- `git status --short` 中与本任务无关的文件。

完成后停止：

- 不 commit；
- 不 push；
- 不运行 OCR；
- 不进入 Stage 5 第二部分。
