# Stage 5 Part 1 Slice 1B-1：GLM 实现交回（Handback）

状态：首轮实现 + Issue 1（Workspace 隔离）与 Issue 2（错绑价格）均已在数据库事实层修复并回归通过

日期：2026-07-27

权威合同：[Spec 002](specs/002-provider-call-cost-foundation.md) / [ADR 001](adr/001-provider-call-and-cny-cost-facts.md)

任务包：[PART_1_SLICE_1B1_GLM_IMPLEMENTATION_PACKET.md](PART_1_SLICE_1B1_GLM_IMPLEMENTATION_PACKET.md)

## 0. 独立验收阻断问题修复状态

独立验收提出两个阻断问题，要求在**数据库事实层**（而非 UI/API）建立可靠约束，并保持 ORM 与 migration 0024 一致。两者均以复合外键技术修复；逐项状态如下。

### Issue 2 — 绑定快照时 provider/model 必须一致（禁止错绑价格）✅ 已修复

在 `provider_calls` 上增加复合外键 `(provider_rate_snapshot_id, provider, model) → provider_rate_snapshots(id, provider, model)`。Postgres MATCH SIMPLE 语义下：`provider_rate_snapshot_id IS NULL`（调用未绑快照）时外键被跳过；一旦绑定，三列必须在快照表中存在，**强制 provider/model 一致**，错绑价格被拒绝。

- 该复合外键的引用目标要求 `provider_rate_snapshots(id, provider, model)` 唯一。`id` 已是主键，故该 UNIQUE **永不可能被违反**，纯为满足复合外键目标而存在（零行为变化，仅多一个冗余索引）。
- 两张表（`provider_calls` / `provider_rate_snapshots`）均为 0024 新建表，**完全在本切片 schema 边界内**，未改既有合同、未触碰 0024 之外的 schema。
- ORM 与 migration 0024 一致：两端均声明该冗余 UNIQUE 与复合外键。
- 真实隔离 Postgres 反例已加：错 provider、错 model 绑定被拒（原始 SQL 即被拒）；匹配绑定与未绑定调用放行。

### Issue 1 — workspace_id 必须与其可选 AgentRun.workspace_id 一致 ✅ 已修复（人工批准 2026-07-27）

用户批准方案 1：对既有 `agent_runs` 表增加冗余 `UNIQUE(id, workspace_id)`（零行为变化，`id` 已是 PK），并在 `provider_calls` 上增加复合外键 `(agent_run_id, workspace_id) → agent_runs(id, workspace_id)`，随 migration 0024 并入。

- MATCH SIMPLE 语义下 `agent_run_id IS NULL`（workspace-only 调用）时外键跳过；非空时强制 workspace 一致，**跨 Workspace 绑定在 DB 层被拒绝**。
- `ON DELETE CASCADE` 在复合外键上是必要的：SQLAlchemy 按声明顺序发射 DDL，复合外键先于简单外键；Postgres 按此顺序检查约束，`NO ACTION` 会在简单 FK 的 CASCADE 生效前阻断删除。此行为已在真实隔离 Postgres 实证（临时脚本，用后即删）。
- ORM 与 migration 0024 一致：两端均声明该冗余 UNIQUE 与复合外键（含 `ondelete="CASCADE"`）。
- 真实隔离 Postgres 测试已加：同 Workspace 绑定放行、跨 Workspace 绑定被拒、workspace-only 调用放行、AgentRun 删除仍级联删除 bound Provider Call。
- migration round-trip 测试已增：upgrade 后 `uq_agent_runs_id_workspace` 与 `fk_provider_calls_run_workspace` 存在；downgrade 后均移除。


## 1. 范围确认

按任务包边界完成：Provider Call、CNY 价格快照、纯 Decimal 成本计算、migration `0024`、focused tests。

- 未接入 Course / Tutor / Practice / RAG 调用链。
- 未新增 API / Web / 公开 schema / 路由 / dashboard。
- 未修改 worker、provider adapter、AgentRun / AgentToolCall 既有公开合同。
- 未做历史 backfill、未调用真实 provider、未引入 embedding / Wolfram / Code Lab 定价。
- 未新增依赖、未修改 Compose、未读取或改动 `.tmp/` 与 `artifacts/`。
- 未运行 OCR（按任务包：1B-1/1B-2/1B-3 结束后统一执行）。
- 未 commit、未 push（见 §6）。

## 2. 修改文件与行为摘要

实现文件（进入本切片边界）：

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| [apps/api/learn_platform_api/db/models.py](../../../apps/api/learn_platform_api/db/models.py) | 修改 | 新增 `ProviderRateSnapshot`、`ProviderCall` 两个独立事实模型；`Numeric`/`Decimal` 引入。**Issue 2 修复**：`ProviderRateSnapshot` 增冗余 `UNIQUE(id, provider, model)`，`ProviderCall` 增复合外键 `fk_provider_calls_snapshot_provider_model`。**Issue 1 修复**：`AgentRun` 增冗余 `UNIQUE(id, workspace_id)`，`ProviderCall` 增复合外键 `fk_provider_calls_run_workspace`（`ondelete="CASCADE"`）。 |
| [apps/api/alembic/versions/0024_add_provider_call_cost_foundation.py](../../../apps/api/alembic/versions/0024_add_provider_call_cost_foundation.py) | 新增 | 纯加性 migration：建两表 + 索引 + 约束；upgrade 先建 `uq_agent_runs_id_workspace` 再建 `provider_calls`（含复合外键）；downgrade 先 drop `provider_calls` 再移除唯一约束。**Issue 2 修复**：migration 同步声明冗余 UNIQUE 与复合外键。**Issue 1 修复**：migration 同步声明 `agent_runs` 冗余 UNIQUE 与 `provider_calls` 复合外键（`ondelete="CASCADE"`）。 |
| [apps/api/learn_platform_api/services/provider_cost.py](../../../apps/api/learn_platform_api/services/provider_cost.py) | 新增 | 纯 Decimal 成本计算器与集中精度/舍入规则；不 import ORM。 |
| [apps/api/tests/test_provider_cost_calculator.py](../../../apps/api/tests/test_provider_cost_calculator.py) | 新增 | 纯函数成本计算 focused tests。 |
| [apps/api/tests/test_provider_call_orm.py](../../../apps/api/tests/test_provider_call_orm.py) | 新增 | ORM / 约束 / 禁止字段 / 快照不可变 focused tests（SQLite）。 |
| [apps/api/tests/test_provider_call_deletion_postgres.py](../../../apps/api/tests/test_provider_call_deletion_postgres.py) | 新增 | Postgres CASCADE 删除与 FK 强制 focused tests。 |
| [apps/api/tests/test_provider_call_migration_postgres.py](../../../apps/api/tests/test_provider_call_migration_postgres.py) | 新增 | migration `0023→0024→0023` 隔离 Postgres round-trip + 静态加性守卫。**Issue 2 修复**：round-trip 增「错绑快照被拒 / 匹配绑定放行」原始 SQL 断言。**Issue 1 修复**：round-trip 增 upgrade 后 `uq_agent_runs_id_workspace` + `fk_provider_calls_run_workspace` 存在断言，downgrade 后均移除断言。 |
| [apps/api/tests/test_provider_call_binding_postgres.py](../../../apps/api/tests/test_provider_call_binding_postgres.py) | 新增 | **Issue 2 修复**：隔离 Postgres 反例——错 provider / 错 model 快照绑定被拒（原始 SQL），匹配绑定与未绑定调用放行。 |
| [apps/api/tests/test_provider_call_workspace_postgres.py](../../../apps/api/tests/test_provider_call_workspace_postgres.py) | 新增 | **Issue 1 修复**：隔离 Postgres 实证——同 Workspace 绑定放行、跨 Workspace 绑定被拒（原始 SQL）、workspace-only 调用放行、AgentRun 删除仍级联删除 bound Provider Call。 |


行为摘要：

- `ProviderRateSnapshot`：append-only 的 CNY 价格快照。固定 `currency=CNY`，Decimal `input/output_rate_per_1m`，`(provider, model, effective_at)` 唯一，非负费率。无 update/delete 业务方法。
- `ProviderCall`：一次真实 provider 请求尝试。必填 workspace owner，可选 agent_run owner；稳定 `ordinal`/`phase`；provider/model 快照；`started|succeeded|failed|timed_out|canceled`；可空 input/output tokens、latency、稳定 `error_code`；开始/完成时间；可选价格快照引用。不保存 prompt/message/evidence/answer/原始响应/原始错误。
- `calculate_cost`：纯函数 `tokens * rate_per_1m / 1,000,000`；只有 provider+model+双维 usage+双维 rate 完整时返回 CNY Decimal；`0` token 是有效零成本；缺失返回单一稳定 unknown reason，优先级 `provider_missing > model_missing > usage_missing > rate_missing`；空白 provider/model 视为 missing；不使用 float、不读当前配置、不把派生总成本回写 Provider Call。

## 3. schema / 约束 / Decimal 规则

### Provider rate snapshot 约束

- `currency = 'CNY'`（DB CHECK + server_default）。
- `input_rate_per_1m >= 0`、`output_rate_per_1m >= 0`（DB CHECK）。
- `UNIQUE (provider, model, effective_at)`（append-only 防重）。
- `Numeric(RATE_NUMERIC_PRECISION=16, RATE_NUMERIC_SCALE=8)`，集中定义于 `provider_cost.py`，由 `db.models` 复用，避免精度散落。

### Provider call 约束

- `workspace_id` NOT NULL，FK `workspaces.id ON DELETE CASCADE`。
- `agent_run_id` nullable，FK `agent_runs.id ON DELETE CASCADE`（绑定 AgentRun 时随其删除）。
- `ordinal >= 0`、`status IN (started|succeeded|failed|timed_out|canceled)`、`input_tokens/output_tokens/latency_ms` nullable 但非负（DB CHECK）。
- `provider_rate_snapshot_id` nullable，FK `provider_rate_snapshots.id`（无 ondelete → 默认 RESTRICT，已引用的快照不可删，保护历史）。
- **Issue 2 绑定完整性（DB 事实层）**：复合外键 `(provider_rate_snapshot_id, provider, model) → provider_rate_snapshots(id, provider, model)`（`fk_provider_calls_snapshot_provider_model`）。MATCH SIMPLE 语义：`provider_rate_snapshot_id IS NULL`（未绑快照）时外键跳过；绑定时三列必须在快照表存在，**强制 provider/model 与快照一致，禁止错绑价格**（原始 SQL 亦被拒）。引用目标 `provider_rate_snapshots(id, provider, model)` 因 `id` 为主键而永不可能违反，该 UNIQUE 仅用于满足复合外键目标。
- **Issue 1 Workspace 隔离（DB 事实层，人工批准 2026-07-27）**：复合外键 `(agent_run_id, workspace_id) → agent_runs(id, workspace_id)`（`fk_provider_calls_run_workspace`，`ON DELETE CASCADE`）。MATCH SIMPLE 语义：`agent_run_id IS NULL`（workspace-only 调用）时外键跳过；非空时**强制 workspace 一致，跨 Workspace 绑定被拒**。`ON DELETE CASCADE` 是必要的：SQLAlchemy DDL 顺序使复合外键先于简单外键，Postgres 按此顺序检查，`NO ACTION` 会阻断删除。引用目标 `agent_runs(id, workspace_id)` 因 `id` 为主键而永不可能违反，该 UNIQUE 仅用于满足复合外键目标。
- 偏序唯一索引 `uq_provider_calls_run_ordinal ON (agent_run_id, ordinal) WHERE agent_run_id IS NOT NULL`：同一 Run 内 ordinal 唯一；workspace-only 调用不参与。migration 用跨方言 `op.execute` 原始 SQL，PG 与 SQLite 均生效。

### Decimal 规则（集中定义）

- `TOKENS_PER_MILLION = 1_000_000`。
- `COST_NUMERIC_PRECISION=16 / COST_NUMERIC_SCALE=8`；`cost_quantum() = 1e-8`。
- `COST_ROUNDING = ROUND_HALF_UP`；计算结果 `quantize(cost_quantum(), ROUND_HALF_UP)`。
- 仅用于返回给调用方的 Decimal；不持久化到 Provider Call（ADR 001 §4.6）。

## 4. 实际运行的命令与逐项结果

环境：Windows（Git Bash 执行）；仓库 `.venv-test`（`psycopg 3.3.4` / `sqlalchemy 2.0.51` / `alembic 1.18.5` / `pytest 8.4.2`，`Python 3.13.5`）；CWD = `apps/api`（`conftest.py` 处理 sys.path）；本地 Postgres `localhost:55432` 可达，故 PG 测试**实际运行**而非 skip。

逐项结果（Issue 1 + Issue 2 修复回归）：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q tests/test_provider_call_orm.py tests/test_provider_cost_calculator.py` | **34 passed**（19 ORM + 15 calculator）。 |
| `python -m pytest -q tests/test_provider_call_binding_postgres.py` | **4 passed**（真实隔离 PG：错 provider / 错 model 快照绑定被拒；匹配绑定与未绑定调用放行）。 |
| `python -m pytest -q tests/test_provider_call_workspace_postgres.py` | **4 passed**（真实隔离 PG：同 Workspace 放行、跨 Workspace 被拒、workspace-only 放行、AgentRun 删除仍级联）。 |
| `python -m pytest -q tests/test_provider_call_migration_postgres.py` | **2 passed**（静态加性守卫 + 真实 `0023→head→0023` round-trip；round-trip 新增 Issue 2「错绑快照被拒 / 匹配放行」+ Issue 1「唯一约束与复合外键存在/移除」断言）。 |
| `python -m pytest -q tests/test_provider_call_deletion_postgres.py` | **4 passed**（既有 CASCADE / 快照存活 / FK 强制回归不变）。 |
| `python -m pytest -q tests/test_agent_run_api.py`（AgentRun 直接回归） | **24 passed**。 |
| 合计 | **72 passed**（新增 8 + 既有回归 64）。 |


migration round-trip 在隔离 throwaway 库（`slice1b1_mig_*` / `slice1b1_del_*`，用后即弃）执行，从未接触开发库 `hello_agents`。alembic 通过子进程运行，`DATABASE_URL` 指向 throwaway 库（pydantic-settings 中 env var 优先于 `.env`）。

## 5. 未运行检查及原因

- **未运行真实 OCR**：按任务包 §6，三个 1B 小切片结束后统一执行白名单分块 OCR；本切片不单独跑。
- **未运行 1B-2 / 1B-3 内容**：超出本切片边界（调用链接入、安全读取 API）。
- 未运行整个 `apps/api/tests` 全量：任务包只要求 focused tests + `test_agent_run_api.py` 回归；未要求全量，避免与本切片无关的既有用例噪声。

## 6. 已知风险、合同疑点与建议

对前序遗留实现的一处修正（透明记录）：

- `tests/test_provider_cost_calculator.py::test_unknown_reason_priority_chain_is_locked` 原实现只在每步 `facts.update` **之后**计算，第一步即填入 provider，因此从未评估“全缺失”状态，断言与 calculator 正确行为不符而失败。calculator 实现正确（另三个优先级测试与全 None→`provider_missing` 用例均通过）。已修正该测试序列：在循环起始增加一次“全缺失”计算以观察 `provider_missing`。属 focused cost test 边界内修正，未改变任何产品行为。

合同疑点 / 设计说明（均非阻断）：

1. `ProviderCall` / `ProviderRateSnapshot` 未定义 SQLAlchemy `relationship()`；级联完全依赖 DB 层 `ON DELETE CASCADE`，与仓库既有模型一致，已在 Postgres 实证。读取层（1B-3）如需 ORM 关系可再补，不影响本切片合同。
2. `provider_calls.provider_rate_snapshot_id` 无 `ondelete`，默认 RESTRICT：已被引用的快照不可删，符合 append-only 与“历史不随配置变化”（Spec 002 §2 / ADR 001）。属有意设计。
3. calculator 只按“存在性”判定 unknown，不在领域层重复校验非负（符号完整性由 DB CHECK 保证），与 Spec 002 §2 一致；已在 `provider_cost.py` docstring 说明。
4. migration 偏序唯一索引用 `op.execute` 原始 SQL 以跨 PG/SQLite 可移植；两方言均已验证。
5. 本次修复验证使用仓库当前实际暴露的 `.venv-test`（`Python 3.13.5`，包版本与首轮一致）。前序 handback 曾称 `.venv`，但当前仓库仅存在 `.venv-test`；两 venv 包版本相同，结果可比。

建议：**Issue 1（Workspace 隔离）与 Issue 2（错绑价格）均已在 DB 事实层修复并以隔离 Postgres 反例锁定**，可进入验收。

## 7. 提交状态

- **未 commit。**
- **未 push。**

所有改动保留为工作区改动（含未跟踪新文件 `tests/test_provider_call_binding_postgres.py`、`tests/test_provider_call_workspace_postgres.py`），交由用户/验收决定提交时点。

本次按独立验收要求修复阻断问题：**Issue 1（Workspace 隔离）与 Issue 2（错绑价格）均已在 DB 事实层修复并回归通过**。已更新本 handback，现停止，未进入 1B-2。
