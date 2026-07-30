# Stage 5 Part 2 Slice 2B — Batch A GLM Handback

状态：Batch A 实现候选交回，等待 Codex 独立验收。**未进入 Batch B。**

日期：2026-07-29

执行者：GLM（实现），在已接受 Spec 007 / Spec 006 / ADR 003 / ADR 004 / Stage 4 Spec 004-005 /
ADR 006-007 与本任务包合同内工作。

## 0. 交回结论摘要

Batch A 在 `apps/api/tests/quality_baseline/` 下建立了 Spec 007 的四条优化前基线：

1. Python/Java/C++ 受控编程练习基线（真实 `execute_generation` / `execute_grading` + 真实本地
   toolchain 的 canonical harness，标记 `controlled_backend`，非真实 Judge0）；
2. 总题数 `1/3/5/10` 的预算曲线（general_only / require_coding / require_science，按总题数测试，
   无“编程题数量”参数）；
3. Practice 科学题 Wolfram 调用漏斗（required/optional/forbidden + 各阶段失败分类）；
4. Tutor code execution / Wolfram 双 MCP 漏斗（必要/不必要/未授权/失败降级）。

新增 124 个受控测试，全部经过真实产品 service/orchestration 入口，在隔离 Postgres 上运行，
**124/124 通过**。`git diff --check` 通过。**产品代码零修改**（见 §10）。

> **验收修正轮（2026-07-29，针对 `PART_2_SLICE_2B_BATCH_A_ACCEPTANCE_FIX_PACKET.md`）已关闭两个阻断项。**
> 原先如实报告的 §11 四文件回归失败（SQLite `database is locked` / 跨库外键）**已修复并零失败**；
> C++ controlled compiler Gate 的诊断已从“只给退出码”升级为脱敏、长度受限、含编译器版本与隔离
> 子探针的稳定诊断。正式 Postgres durable-fact 合同未被削弱。详见下方 **§13 验收修正轮**。**未进入 Batch B。**

## 1. 实际修改 / 新增文件

全部位于 `apps/api/tests/quality_baseline/`（新建包，untracked）。**未修改任何已跟踪文件，
未修改任何产品代码、schema、Compose、CI、Web、`tests/system/**`、`apps/mcp_execution/**`。**

| 文件 | 行数 | 职责 |
|---|---:|---|
| `__init__.py` | — | 包标识 + 边界说明 |
| `conftest.py` | 69 | `pg_db` 随机一次性 Postgres fixture + Postgres Gate（不可达即 FAIL，不 skip、不回退 SQLite） |
| `samples.py` | 382 | 机器可读 allowlist 样本合同（脱敏） |
| `report.py` | 222 | `RunRecord` + 11 类科学工具分类器 + 序列化白名单 + 禁止字段防线 |
| `pgsupport.py` | 465 | 脱敏 seed helper、`_make_settings`、NEW-session 查询 helper、orchestration 预备 |
| `controlled.py` | 497 | 受控 backend：真实本地 toolchain 的 canonical harness 执行、scripted provider、science verifier、tutor science backend、合法 artifact 构造器 |
| `test_sample_contract.py` | 114 | 样本合同（11 测试） |
| `test_report_contract.py` | 106 | 报告白名单 + 11 分类器 + 禁止字段防线（58 测试） |
| `test_coding_baseline.py` | 336 | 三语言编程基线矩阵（19 测试） |
| `test_budget_curve.py` | 219 | 总题数预算曲线（18 测试） |
| `test_practice_wolfram_funnel.py` | 351 | Practice Wolfram 漏斗（11 测试） |
| `test_tutor_mcp_funnel.py` | 237 | Tutor 双 MCP 漏斗（7 测试） |

未新增结果目录：Batch A 测试全部内联断言，不写盘 raw artifact；故未新增 `.gitignore` 忽略项
（`__pycache__` 已被既有忽略规则覆盖）。

## 2. 每类样本及稳定 ID

`samples.py::REGISTRY` 共 11 个脱敏样本。每个样本只保存：`sample_id`、能力轴、脱敏
objective/evidence 类别、结构性 `computational_property`（说明工具为何 required/optional/forbidden）、
请求模式与总题数、单一语言、`required|optional|forbidden`、待验证合同分类、结构型 `profile`
（驱动真实 `determine_suitability`）、`objective_variants`（≥2 措辞变体）与 `anti_signals`（≥1 反例）。
**不包含**真实题干、答案、reference code、hidden tests、prompt、provider 原文、key、URL 或绝对路径
（由 `test_no_sample_carries_forbidden_fields` 强制）。

| 稳定 sample_id | 能力 | 工具预期 | 语言 | 说明（脱敏） |
|---|---|---|---|---|
| `practice_coding_identity` | practice_coding | required | python | 确定性 UTF-8 串变换 |
| `practice_coding_reverse` | practice_coding | required | java | 串反转（canonical wrapper/多行/UTF-8） |
| `practice_coding_aggregate` | practice_coding | required | cpp | 确定性逐字符聚合 |
| `practice_science_symbolic_integral` | practice_science | required | — | 符号不定积分，本地规则无法判定 |
| `practice_science_unit_constant` | practice_science | required | — | 物理常量/单位计算 |
| `practice_science_local_numeric` | practice_science | optional | — | 带容差数值，本地规则充分 |
| `negative_concept_engineering` | negative_control | forbidden | — | 纯概念权衡，无可执行/可计算目标 |
| `tutor_code_required` | tutor_code | required | python | 需运行小程序观察行为 |
| `tutor_code_not_needed` | tutor_code | forbidden | python | 概念解释，代码无增值 |
| `tutor_science_required` | tutor_science | required | — | 符号计算问题 |
| `tutor_science_not_needed` | tutor_science | forbidden | — | 定义/概念问题 |

满足 Spec 007 §4.1 最低集合：≥2 编程正例、≥2 科学正例、1 概念负对照、Tutor code 与 Wolfram
必要/不必要各一；并额外覆盖 `optional` 科学样本与 C++ 语言。

反硬编码：`__post_init__` 强制 required/forbidden 样本必须带 ≥2 措辞变体与 ≥1 反例；
`test_suitability_is_structural_not_keyword_based_counterfactual` 证明相同 objective 文本但不同
结构 flag 得到不同 suitability（结构判定，非关键词）。

## 3. 报告 schema 与敏感字段防线（Section 6）

`report.py`：

- `RunRecord` 仅含聚合字段与稳定分类（sample_id、能力、语言、请求模式、请求/最终题数、题型计数、
  tool requested/authorized/called/succeeded、各阶段状态、provider phase/status/usage/finish_reason、
  repair/provider/MCP/step 计数、稳定失败阶段与类别、latency、token、CNY cost 或 unknown_reason、
  `controlled_backend` 标记）。
- `classify_science_tool_run(facts)` 由结构化事实推导 11 类
  （`tool_not_needed` / `tool_request_missed` / `authorization_missing` / `capability_unavailable` /
  `schema_drift` / `mcp_connection_failed` / `tool_result_invalid` / `scientific_reference_unverified` /
  `artifact_failed_after_tool_success` / `succeeded_with_wolfram` / `succeeded_without_wolfram`），
  **不解析异常正文/日志/自然语言**（`test_classifier_ignores_natural_language_and_exception_bodies`）。
- `serialize()` 只输出 `ALLOWED_SNAPSHOT_KEYS` 并经 `assert_snapshot_safe()`；
  `FORBIDDEN_FIELD_NAMES` 覆盖 prompt/messages、lesson/source/evidence、stem/answer/rubric、
  source/reference/student code、hidden/public tests、harness、compiler/Wolfram 原文、key、Authorization、
  URL、绝对路径等；`_FORBIDDEN_VALUE_SUBSTRINGS` 拒绝 `Authorization`/`Bearer`/`http(s)://`/
  `C:\`/`/home/`/`/tmp/`/`.env`/`run_code`/`WolframLanguageEvaluator` 等。
- 防线测试：`test_snapshot_rejects_every_forbidden_field_name`（逐字段）、
  `test_snapshot_rejects_forbidden_value_substrings`（逐子串）、
  `test_allowed_and_forbidden_key_sets_are_disjoint`、`test_classifier_reaches_every_category`（11 类全可达）。

## 4. 三语言编程基线矩阵（Section 7）

全部经过真实 `practice_generation.execute_generation` / `execute_grading`，受控 backend
`controlled_execute_code_run_sync` 运行**真实产品 canonical harness**
（`_build_coding_harness_for_version`）于**真实本地 `python` / `javac` / `g++` toolchain**。
标记 `controlled_backend`，**绝不报告为真实 Judge0**（`test_compile_error_is_classified_not_reported_as_judge0`
断言 `controlled.CONTROLLED_BACKEND is True`）。

覆盖（19 测试，参数化 python/java/cpp）：

- 初始成功（reference 全测通过 → Set 发布、`ValidateCodingReference` succeeded、ProviderCall plan+generation）；
- specialized repair 成功（初始 broken → 单题 minimal repair DTO → 修复后重验通过，phase 含 `repair`）；
- reference 编译失败（java/cpp 真实语法错误 → 稳定 `coding_reference_compile_failed`/`coding_repair_revalidation_failed`，零半成品 Set）；
- reference 测试不一致（全语言：编译通过但输出错误 → `coding_reference_test_failed`/`coding_repair_revalidation_failed`，零半成品）；
- 正确提交评分 100、代表性错误提交评分 0（`CodeExecution` AgentToolCall）；
- Java canonical wrapper（`public class Solution` 归一化）、C++ bare `string` + provider includes、
  UTF-8（Latin+CJK）与多行 I/O round-trip、compile-error 分类（全语言经真实 harness）。

Python 为对照组：其 SyntaxError 为 runtime 分类（无 compile-error），与 Java/C++ 区分，且不被
Java/C++ 结果替代（每语言独立参数化运行）。

## 5. 题数矩阵与 specialized item 真实语义（Section 8）

`item_count` 为 Set 总题数（1..10）。`require_coding`/`require_science` 只要求对应 specialized item
存在；v2 每 Set 最多一个 specialized item，其余为普通题。**未虚构“编程题数量”参数。**

覆盖（18 测试）：general_only / require_coding / require_science × `1/3/5/10` 成功矩阵
（最终题数精确 == 总题数、specialized ≤ 1、phase plan+generation、usage 非 null）；
`test_specialized_item_never_exceeds_one_at_high_count`（10 题 == 1 coding + 9 普通）；
`test_multiple_specialized_items_are_rejected`（双 coding 反例被拒、零 Set）；
`test_budget_exhausted_via_length_finish_reason`（`finish_reason="length"` → `practice_budget_exceeded`，零半成品）；
`test_budget_curve_failure_phase_is_classifiable`（非法 artifact → 稳定 structure/citation code）；
`test_silent_reduction_is_auditable_not_relabelled`（provider 少返回题时，权威 Set `item_count`==实际、
`generation_config.item_count`==请求，差异可审计，不冒充全数成功）；
`test_budget_settings_are_not_modified`（v2 统一预算 `max_provider_calls==4`、`max_attempt_steps==12` 运行前后不变）。

## 6. Practice / Tutor Wolfram 与 code MCP 漏斗（Section 9）

### 6.1 Practice Wolfram（11 测试，`test_practice_wolfram_funnel.py`）

真实 `execute_generation` / `execute_grading`；science seam 为 spying 受控
`execute_science_verification`（捕获 `ScienceToolResult`，绝不联网 Wolfram Cloud）。分类由结构化事实
（scripted `needs_remote`、捕获的 verifier 结果、NEW-session 查询的 Set/Job 状态）经
`classify_science_tool_run` 推导。覆盖：

- `succeeded_with_wolfram`（required+proposed+authorized+受控 MCP 成功 → Set 发布、`VerifyScientificAnswer` succeeded）；
- `succeeded_without_wolfram`（optional 本地数值，零远程调用）；
- `tool_request_missed`（required 样本但 provider 设 `needs_remote=False`）；
- `capability_unavailable`（projection 未 ready → `create_generation_job` 拒绝 `science_computation_unavailable`）；
- `schema_drift` / `mcp_connection_failed` / `tool_result_invalid`（受控 verifier 各阶段失败 → Job 失败、零 Set、私有子码不持久化、`controlled_backend=True`）；
- `scientific_reference_unverified`（tool 成功但 observation 未验证 → 修复后仍失败）；
- forbidden 负对照（概念课节 `require_science` → `science_item_not_supported_by_lesson`，零调用，`tool_not_needed`）；
- 评分本地充分零调用；评分需远程则调用并记 `VerifyScientificAttempt`。

复用既有 Wolfram allowlist（`WolframAlpha`/`WolframContext`）；测试不出现 `WolframLanguageEvaluator`
（被产品 allowlist 永拒，并由 report 禁止子串防线二次拦截）。

### 6.2 Tutor 双 MCP（7 测试，`test_tutor_mcp_funnel.py`）

真实 `tutor_generation.execute_tutor_turn`（course scope）。code seam 为受控
`code_lab_execution.execute_code_run_sync`；science seam 为受控
`tutor_generation._execute_science_tool_call`（最低层 fake backend，§9.2 允许；鉴权/预算/降级逻辑仍为真实）。
覆盖：code required+authorized→`McpCodeTool` succeeded；science required+authorized→`McpScienceTool` succeeded
（并 `WolframAlpha`/`WolframContext` allowlist）；required 但模型未请求→`tool_request_missed`；
authorized 负对照→零调用（authorization 未消耗）；unauthorized→零调用（无 auth 行、请求被强清）；
tool 失败→`McpScienceTool` failed + answer 含 limitation 块（不伪造已验证）；预算链对应
（`step_count ≤ 8`、MCP ≤ 3、Turn/AgentRun/ProviderCall/AgentToolCall 对应）。

## 7. 测试是否经过真实产品入口 / monkeypatch 边界

每条关键证据从 NEW Postgres Session 查询（`pgsupport.q_*`），不以 mock 调用次数为唯一证据，
不手工创建期望 AgentRun/ToolCall。

| 入口 | 真实产品函数 | 允许的 monkeypatch 边界（最低层） |
|---|---|---|
| Practice 生成 | `practice.create_generation_job` + `practice_generation.execute_generation` | `practice_generation.call_practice_provider`、`practice_generation.retrieve`、`practice_generation.execute_code_run_sync`（真实 harness+本地 toolchain）、`science_tool_service.execute_science_verification`、`readiness._read_capability_projection`、`practice.enqueue_practice_job` |
| Practice 评分 | `practice.submit_attempt` + `practice_generation.execute_grading` | 同上 + `practice_generation.call_provider` |
| Tutor Turn | `tutor.create_session` + `tutor.create_turn` + `tutor_generation.execute_tutor_turn` | `tutor_generation.call_provider`、`tutor_generation._search`、`code_lab_execution.execute_code_run_sync`、`tutor_generation._execute_science_tool_call`、`readiness._read_capability_projection`、`tutor.enqueue_tutor_turn` |

反事实：`_multiple_specialized_items_are_rejected`、`_reference_compile_failure_rejects_set`、
`_reference_test_mismatch_rejects_set`、`_budget_exhausted_via_length_finish_reason`、
`_tutor_unauthorized_blocks_call`、`_tutor_science_failure_yields_limitation` 等证明破坏产品边界会让测试失败。

## 8. 实际执行命令和精确结果

命令使用仓库 `.venv`（Python 3.12.13，psycopg 3.3.4，pytest 8.4.2；`javac`/`g++`/`java` 均在 PATH 且可编译）。

1. 新增 focused 测试：
   `.venv/Scripts/python.exe -m pytest -q apps/api/tests/quality_baseline/`
   → **124 passed in 148.13s**（test_sample_contract 11、test_report_contract 58、test_coding_baseline 19、
   test_budget_curve 18、test_practice_wolfram_funnel 11、test_tutor_mcp_funnel 7）。
2. 任务包 §11 四文件：
   `.venv/Scripts/python.exe -m pytest -q apps/api/tests/test_stage4_eval.py apps/api/tests/test_slice5_practice_stability.py apps/api/tests/test_slice5_practice_worker.py apps/api/tests/test_provider_call_chain_behavior.py`
   → **100 passed, 5 failed in 224.25s**。
3. `git diff --check`（含新增文件经 `add -N`）→ **exit 0**（无空白错误）。

Postgres：`localhost:55432`，凭据 `hello_agents:hello_agents`；每个 Postgres 测试用随机一次性库
`slice2b_batcha_<12hex>`，`create_all` 建表，结束 `DROP DATABASE`；不连开发库、不跑 Alembic。
`psycopg` 直接 import，缺失即 FAIL（conftest 顶层 `import psycopg`）。

### 8.1 §11 五个失败的如实归类（非 Batch A 引入）

5 个失败全部为 `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked`，
SQL 为 recorder 独立 session 的 `INSERT INTO provider_calls ...`，位于：

- `test_stage4_eval.py::test_offline_runner_passes_hard_gates_and_writes_safe_report`
- `test_slice5_practice_stability.py::test_v2_coding_reference_failure_repairs_only_the_failed_item`
- `test_slice5_practice_stability.py::test_repair_immutability_integration_rejects_tampered_hidden_tests`
- `test_slice5_practice_stability.py::test_repair_immutability_inside_exception_block_produces_stable_code`
- `test_slice5_practice_worker.py::test_v2_science_local_rule_decided_does_not_call_remote`

判定与 Batch A 无因果关系：

- 这 5 个测试文件与 `provider_call_recorder.py`、`conftest.py` 均为 Batch A **未编写、未修改**的文件；
  其中 `provider_call_recorder.py` / `conftest.py` 在本会话开始的 `git status` 中已是 `M`（Slice 2A 未提交改动）。
- 单独运行（`pytest <one test>`）同样复现 `database is locked`，说明是 dirty tree 中 SQLite recorder
  独立 session 写并发问题，非并行负载抖动。
- Batch A 的全部测试使用隔离 **Postgres**（非 SQLite），124/124 通过，不受此 SQLite 锁问题影响；
  这也印证 Spec 006 / ADR 003 选择 Postgres 作为系统测试事实来源的必要性。
- Batch A 包的 `conftest.py`（含 `import psycopg` 与 PG 不可达即 raise 的 Gate）作用域仅限
  `quality_baseline/`，四文件运行不收集该包，无侧效应。

**未自行裁决、未修改这些既有文件或产品代码**（受任务包 §4.1 / §10 约束）。作为 dirty tree 既有
（Slice 2A recorder/conftest 改动与 Stage 4 测试的交互）+ 本机 SQLite 行为问题，移交 Codex 复核：
建议 Codex 在干净树上独立复跑确认，并决定是否需要调整 recorder 独立 session 的 SQLite
`busy_timeout` 或将该子集迁至 Postgres（属 Batch B / 第三部分输入，不在本轮处理）。

## 9. 未运行项及原因

- 真实 provider / Judge0 VM / Wolfram Cloud MCP：**未运行**（任务包禁止 GLM 接触真实 key 与远程付费调用）；
  Batch A 全部为受控 provider/fake backend，相关状态只记 `controlled_backend=True`，**未把 fake backend 通过写成真实 Judge0/Wolfram 已通过**。
- 浏览器 / Playwright / Compose 全栈 / CI workflow：**未运行**（属 Batch B，本轮禁止）。
- OCR：**未运行**（任务包禁止）。
- `commit` / `push`：**未执行**。
- Web lint/build：**未运行**（不允许修改 `apps/web/**`，且 Batch A 不要求）。

## 10. Batch B 所需输入

1. 受控 Compose：启动 Practice worker、execution MCP（接 `FakeExecutionBackend`）、fake Wolfram MCP，
   复用 Slice 2A 的 model-services stub 与 ProviderCall 事实。
2. Java/C++ 完整 Chromium Playwright 生成→作答→评分→运行记录路径（本轮已验证非浏览器 orchestration
   入口与 canonical wrapper/UTF-8/多行/编译分类；Batch B 补浏览器层）。
3. scientific Practice Wolfram required/负对照、Tutor code/Wolfram required/负对照的浏览器路径。
4. CI 的 controlled/compiler/browser Gate 接入（本轮 compiler matrix 已在本地真实 toolchain 通过，
   可作为 compiler Gate 基础）。
5. §8.1 的 SQLite recorder 锁问题：建议 Codex 在干净树复跑 §11 四文件确认是否为 dirty tree 既有问题，
   决定 recorder 独立 session 的 SQLite 处理或迁移；如确属产品/fixture 缺陷，作为第三部分输入。
6. 真实 provider/Judge0/Wolfram 人工 Gate 仍由 Codex 在 Batch A 验收后单独触发；本轮只标记
   `remote_not_run`，不宣布 Slice 2B 完成。

## 11. 产品代码零修改证明

- 本会话全部 `Write`/`Edit` 调用路径均位于 `apps/api/tests/quality_baseline/**`（见 §1）。
- 会话开始 `git status --short --branch` 即显示 `apps/api/learn_platform_api/services/{answers,
  course_generation,practice_generation,provider_call_recorder,tutor_generation}.py` 与
  `apps/api/tests/conftest.py` 为 `M`（Slice 2A 既有 dirty 改动），与本轮无关；这些文件本轮**未被触碰**。
- `git status --short apps/api/learn_platform_api/` 与 Batch A 新增对照：唯一新增是 untracked 的
  `apps/api/tests/quality_baseline/`；产品树相对会话起点无任何由 Batch A 引入的改动。
- `git diff --check` exit 0。

## 12. 确认

- 未 `commit`、未 `push`。
- 未运行 OCR。
- 未进入 Batch B、未进入 Stage 5 第三部分。
- 未读取或修改 `.tmp/`、`artifacts/`。
- 未安装依赖；未调用真实 provider/Judge0/Wolfram。
- Postgres Gate 在不可达/依赖缺失时 FAIL（不 skip、不回退 SQLite），已在 `conftest.py` 落实。
- 报告只保存任务包允许的聚合字段与稳定分类；不保存 prompt、题干、答案、代码、tests、compiler/Wolfram
  原文、密钥、URL 或绝对路径（`report.py` 白名单 + 禁止字段防线 + 对应测试）。

若任务包与已接受 Spec/ADR 冲突：本轮未发现需停止的合同冲突；唯一需上交的是 §8.1 dirty tree 既有
SQLite recorder 锁问题（非合同冲突，属既有实现/环境问题），已停止对该部分的处理并如实报告，等待 Codex 裁决。

---

## 13. 验收修正轮（2026-07-29）

依据：`PART_2_SLICE_2B_BATCH_A_ACCEPTANCE_FIX_PACKET.md`。本轮**只**关闭其 §3、§4 两个阻断项，
**未进入 Batch B**。完成并交回 Codex 独立验收。

### 13.1 阻断项一：旧回归真实通过 —— 根因与修正

**先证明每个失败实际使用的 Session/engine（任务包 §3.2 要求）**：在仓库 `.venv`（Python 3.12.13）
独立复跑，逐个失败定位到两条不同的真实根因，均由 Slice 2A 的“recorder 使用独立 Session”改动触发：

1. **Stage 4 offline eval（`test_stage4_eval.py::test_offline_runner_passes_hard_gates_and_writes_safe_report`）**
   —— eval runner 的 `fresh_db()` 用 `:memory:` + `StaticPool` 建业务 Session，但**没有**暴露
   `_test_session_factory`。recorder 的 `record_provider_call` 检测不到该 factory，**回退到产品
   `SessionLocal`（Postgres，`localhost:55432`）**，于是把 ProviderCall 写进 Postgres，而 owner
   `agent_run_id`/`workspace_id` 只存在于内存 SQLite —— 复现为
   `psycopg.errors.ForeignKeyViolation ... fk_provider_calls_run_workspace ... is not present in table "agent_runs"`。
   这正是任务包 §3.1 所述“内存 SQLite 会话与 recorder 默认 Postgres SessionFactory 混用”。

2. **Slice 5 stability/worker 与 chain behavior（其余 4 个失败）** —— 这些测试用 `tests/conftest.py`
   的 `db_session` 文件 SQLite fixture，其 `_test_session_factory` 已暴露（同一 engine）。但默认
   `QueuePool` 会让 recorder 的独立 Session**另开一条连接**到同一文件；当业务 Session 在 provider 调用
   前后持有打开的读事务（`_check_active` 的 `refresh`/`get`）+ 未提交脏写时，SQLite 单写者 + WAL 跨
   快照规则使第二条连接的写死锁，复现为 `sqlite3.OperationalError: database is locked`
   （每次失败耗时 ~35s = busy_timeout 到期）。

**判定**：SQLite 单写者模型无法表达 ADR 004“与调用方打开的业务事务并发的独立写事务”。任务包 §3.2
明确允许“SQLite 仅作 legacy eval/test 兼容路径”与“优先修 fixture/runner”。

**修正（仅 test/eval，未触产品 recorder）**：

- `apps/api/tests/conftest.py::db_session`：文件 SQLite engine 改用 `poolclass=StaticPool`，使
  recorder 的独立 Session 与业务 Session **共用同一条连接**，从而把 recorder 的“独立提交”在该连接上
  串行化，消除第二条写者连接的锁竞争。移除了只对多连接有效的 `PRAGMA journal_mode=WAL` 与
  `timeout`（单连接无需 busy_timeout）。`_test_session_factory` 继续暴露。
- `apps/api/stage4_eval/runner.py::fresh_db()`：保留 `:memory:` + `StaticPool`，新增
  `db._test_session_factory = factory`，使 recorder 走本内存 SQLite engine，而**不再回退 Postgres**。

**为何不算削弱 ADR 004（任务包 §3.2 第二块证明）**：durable “survive-rollback” 是 **Postgres** 正式
合同，由 `test_provider_call_recorder.py`（含 survive-rollback）、`test_acceptance_evidence_*`、
`test_four_chain_orchestration_postgres.py` 在**随机 throwaway Postgres** 上验证，**本次未改产品
`provider_call_recorder.py`、未改 Postgres 路径**。SQLite 上 survive-rollback 仍成立：StaticPool 下
recorder 的提交（无论业务 Session 空闲或持事务）都能跨随后的业务 rollback 存活——已用最小探针实证
（idle 与 mid-transaction 两种场景均存活）。即：legacy SQLite/eval 只要求 recorder“能跑、不锁”，
durable 事实仍由 Postgres 承担。

**未做、且符合约束**：未 skip/xfail、未删断言、未吞异常、未关外键、未禁用 recorder、未伪造
ProviderCall、未把 legacy eval 静默接到开发 Postgres、未迁移 legacy eval 到 Postgres。

### 13.2 阻断项二：C++ controlled compiler Gate —— 根因与诊断升级

**独立复跑（任务包 §4）**：

- 直接复跑最小 C++ 预检（命令行 `g++ -std=c++17 -fexec-charset=UTF-8 preflight.cpp -o ...` 与
  Python `subprocess` 两条路径）：在 GLM 与本独立环境均 `rc=0`，g++ 可用。
- 复跑 C++ generation/harness 用例：`test_coding_baseline.py`（19 项，含 cpp 参数化的初始成功、
  specialized repair、reference compile failure、test mismatch、grading、canonical wrapper、UTF-8
  多行、compile-error 分类）全过。

**实际编译器事实（脱敏）**：`g++` 在 PATH，`--version` 首行
`g++ (Rev5, Built by MSYS2 project) 16.1.0`；`javac 21.0.9`；`python.exe`。三者在本环境均通过预检。

**Codex 抽验 `rc=1` 无法复现的根因判定**：本环境（含 Python `subprocess` 路径、cp936 locale）不能
复现 rc=1；Codex 的 rc=1 是环境相关的，而其真正原因被**旧预检丢弃了 g++ 的 stderr**（旧诊断仅
`"g++ present but trivial compile failed rc=1"`）。最可能的环境性成因落在：g++ 输出在非 UTF-8 系统
locale 下的解码、temp 路径含 g++ Windows 路径处理不能接受的字符、运行库/DLL 解析或杀软拦截输出 exe。

**修正（`apps/api/tests/quality_baseline/controlled.py`，test-only）**：

- `_preflight` 失败诊断从“只给退出码”升级为：`{binary} present ({version}) but trivial compile failed
  rc={rc}; detail={脱敏 stderr+stdout 摘要}{isolation}`。
  - `detail`：经 `_redact()` 脱敏——替换 temp 目录为 `<tmp>`、用正则把任何 `C:\…` / `/…` 绝对路径替换
    为 `<path>`、折叠空白、截断 ≤400 字符；**不含绝对路径**。
  - `version`：取 `--version` 首行并同样脱敏。
  - `isolation` 子探针（仅 cpp）：用**同一源码、去掉 `-std=c++17`/`-fexec-charset=UTF-8`** 再编译
    一次，报告 `bare_compile_rc`。`bare_compile_rc=0` ⇒ 失败定位到 flag/iconv（如 `-fexec-charset` 在
    缺 iconv 的构建上失败）；`bare_compile_rc≠0` ⇒ 编译器/运行库/temp 环境本身故障。这把“环境 / 命令
    参数 / 运行库”几类成因可区分。
- 新增 `_run_subprocess()`：统一 `text=True, encoding="utf-8", errors="replace"`（旧代码不一致——cpp
  run 已是 utf-8，其余用系统 locale cp936 解码，Windows 下既脆弱又可能掩盖真实错误）。`_run_local`
  的 stderr 改用 `_redact()`（旧版只替换 temp 目录，仍可能漏出其他主机绝对路径）。
- python 的“ok”诊断从 `{sys.executable}`（旧版**泄露解释器绝对路径**）改为 `os.path.basename(...)`。

**Gate 仍诚实失败**：编译器缺失/损坏时 `require_toolchain_ok` 照常 `raise RuntimeError`（不 skip、不
xfail、不 Python 代跑、不伪造成功、不移除真实 `g++` Gate），但失败信息现在足以定位问题。

**脱敏诊断实证（模拟 g++ 损坏）**：
- flag-only 失败：`g++ present (g++.exe (MSYS2) 16.1.0) but trivial compile failed rc=1; detail=<path> fatal error: no iconv conversion available bare_compile_rc=0`
- 编译器环境失败：`... rc=1; detail=<path> fatal error: ... bare_compile_rc=1 detail=<path> fatal error: ...`
- 两类均：state=`broken`、无 `C:`、无 temp 目录名、无 `msys`、长度受限、保留真实成因与隔离结果。

### 13.2a C++ Gate 根因确认与受控环境修正（PATH/DLL，第二轮）

Codex 进一步定位并**确认**了 `rc=1` 的真实根因（取代上文“最可能成因”的推断）：

- `g++` 位于 `C:\msys64\ucrt64\bin\g++.exe`，`cc1plus.exe` 存在；但在当前 **Conda base PATH** 下
  `cc1plus` 退出码 **`0xC0000139`（`STATUS_ENTRYPOINT_NOT_FOUND`）**——即加载到了**不兼容的 DLL**
  （Conda base 目录的运行库先于 MSYS2 ucrt64 被加载）。
- 临时把 `C:\msys64\ucrt64\bin` 放到 PATH **首位**后，`cc1plus` 与最小 C++ 编译均退出 0。
- 即：问题不是编译器缺失、不是命令参数、不是编码，而是**子进程继承了会优先加载冲突 DLL 的 PATH**。

**修正（仅 `apps/api/tests/quality_baseline/controlled.py`，test-only；加必要 test-only 测试）**：

- 新增 `_env_with_dir_first(dir)`：返回 `os.environ` 的**全新副本**（保留 SYSTEMROOT/TEMP/PATHEXT 等全部
  变量），仅把指定目录置于 `PATH` 首位；**绝不修改 `os.environ`**（requirement 3）。
- 新增 `_env_for(binary)`：用 `shutil.which(binary)` 解析（名字或绝对路径均可），返回以**该编译器自身目录**
  为 PATH 首位的受控环境；解析不到返回 `None`。**按 binary 逐个解析**，故 Java/Python 绑定各自安装目录、
  绝不绑定 g++ 目录（requirement 1、6）。
- `_run_subprocess(cmd, *, env=None)` 支持显式传入受控环境（requirement 4）；`env=None` 时照常继承 `os.environ`。
- g++ 预检、bare probe、`_run_local` 的 C++ 编译**与 harness 运行**全部使用同一受控环境
  `_env_for("g++")`（requirement 5）——harness `.exe` 动态链接 ucrt64 运行库 DLL，运行步同样需要该目录。
  Java 的 `javac`/`java` 用 JDK 目录；Python 用 `sys.executable` 目录。
- 测试 `test_controlled_env.py` 证明（平台中立，CI `ubuntu-latest` 可移植，详见 §13.2b）：
  1. 受控环境把编译器自身目录置于继承 PATH 中冲突目录**之前**（`parts.index(own) < parts.index(conflict)`），
     且 `os.environ` 不被改动；
  2. 外部 PATH 前部存在冲突目录时，C++ 预检与真实 harness 编译**仍成功**（编译器运行库目录仍优先）；
  3. **spy 断言**（不依赖任一 OS 的 DLL 搜索行为）：在成功路径上，C++ 预检（version 探针 + flagged 编译）
     与真实 harness 编译/运行的**每一个**子进程都收到 PATH 首项为已解析 g++ 目录的受控环境；在失败路径
     （强制 flagged 编译失败以触发 bare probe）上，version 探针、flagged 编译与 bare probe 同样如此；
  4. `require_toolchain_ok` 在编译器缺失时仍 `raise RuntimeError`（诚实失败，不 skip）。

**保留**：现有脱敏（`_redact`：`<tmp>`/`<path>` 替换、折叠空白、≤400 字符）、长度限制、诚实失败 Gate
（requirement 8）全部不变。`_compiler_version` 亦改在受控环境下取 `--version`。

### 13.2b CI 可移植性修正（受控环境测试，第三轮）

**问题**：上轮的 `test_cpp_compile_requires_compiler_runtime_dir_counterfactual` 依赖“把编译器目录从
PATH 删除后必然编译失败”这一**平台特定**假设（Windows/MSYS2 的 DLL 布局）。CI 为 `ubuntu-latest`：在
Linux 上删除 g++ 目录可能直接 `FileNotFoundError`，或 Linux 动态链接器仍能解析运行库，使该断言成为
环境相关的假失败。

**修正（仅 `apps/api/tests/quality_baseline/test_controlled_env.py`，test-only；未改 `controlled.py`）**：
删除该平台特定反例，改为两个**平台中立**的 spy 测试（requirement 4）：

- `test_cpp_success_subprocesses_receive_resolved_gpp_dir_first`：spy 拦截 `_run_subprocess`，驱动真实
  `_preflight("cpp")` + `controlled_execute_code_run_sync("cpp", ...)`；断言成功路径上 version 探针、
  flagged 编译、harness 编译、harness 运行**每一个**子进程收到的 `env["PATH"]` 首项 == 已解析的 g++ 目录。
- `test_cpp_bare_probe_receives_resolved_gpp_dir_first_on_failure`：强制 flagged 编译失败以触发 bare probe，
  断言 version 探针、flagged 编译、bare probe 三者同样收到 g++ 目录首项的受控环境。

这两条直接断言“受控环境被正确接到每个编译子进程上”，不假设任何操作系统的 DLL 搜索行为，因此在
Windows 与 Linux CI 上都成立。**保留的平台中立核心证明**（requirement 3）：
外部 PATH 前置冲突目录时受控环境仍把解析出的编译器目录放首位、`os.environ` 不被修改、真实 g++
preflight/harness 在受控环境中成功、编译器无法解析时 Gate 诚实失败——均由其余测试覆盖，未用
skip/xfail/平台判断掩盖（requirement 2）。`controlled.py` 的已通过实现本轮**未被修改**（requirement 5）。

### 13.3 本轮修改文件与边界理由

| 文件 | 性质 | 改动 | 边界理由 |
|---|---|---|---|
| `apps/api/tests/conftest.py` | test fixture（已 M，Slice 2A） | `db_session` 改 `StaticPool`、去 WAL/timeout | 任务包 §3.2“优先修 fixture”；仅 SQLite legacy backend |
| `apps/api/stage4_eval/runner.py` | eval runner（已 tracked） | `fresh_db()` 暴露 `_test_session_factory` | 任务包 §3.2 允许修“测试 runner”；eval 非 `learn_platform_api/**` 产品码 |
| `apps/api/tests/quality_baseline/controlled.py` | test-only（Batch A 新增，untracked） | 预检诊断升级 + 统一 UTF-8 subprocess + 脱敏 + **受控编译器环境（`_env_for`/`_env_with_dir_first`，PATH 首位置编译器目录，不碰 `os.environ`）** | 任务包 §4；仅 controlled 测试后端 |
| `apps/api/tests/quality_baseline/test_controlled_env.py` | test-only（第二、三轮新增/改写，untracked） | 受控环境测试（8 项，平台中立、CI 可移植：优先级、不污染 `os.environ`、按 binary 解析、冲突 PATH 下仍编译、**spy 断言 preflight/bare/compile/run 的 env 首项为 g++ 目录**、诚实失败 Gate） | 任务包 §4 / requirement 4、7；仅 test |

**未触**：`apps/api/learn_platform_api/**` 产品码（含 `provider_call_recorder.py`）、schema/migration、
Web、Compose、CI、`tests/system/**`、`apps/mcp_execution/**`、真实远程配置。

### 13.4 全部验证结果（精确 passed/failed/skip + 耗时，命令分开跑、未相加冒充）

环境：仓库 `.venv`，Python 3.12.13，pytest 8.4.2，Postgres `localhost:55432`。

1. 任务包 §3 阻断项一 —— 四文件（`test_stage4_eval.py test_slice5_practice_stability.py
   test_slice5_practice_worker.py test_provider_call_chain_behavior.py`）：
   **105 passed, 0 failed, 0 skipped in 104.66s**（修前为 100 passed / 5 failed in 224s）。
2. 任务包 §3 ADR 004 / orchestration 回归（`test_provider_call_recorder.py
   test_acceptance_evidence_wrapper.py test_acceptance_evidence_course_owner.py
   test_acceptance_evidence_rag_trace.py test_four_chain_orchestration_postgres.py`）：
   **83 passed, 0 failed, 0 skipped in 187.40s**。
3. 任务包 §4 C++ Gate（`quality_baseline/test_coding_baseline.py`，**未手工修改 PATH**）：
   **19 passed, 0 failed, 0 skipped**（第一轮 50.74s；第二轮受控环境修正后再跑 55.56s）。
4. 任务包 §6（`quality_baseline/` 全量）：**132 passed, 0 failed, 0 skipped in 145.24s**
   （= 124 原有 + 8 项 `test_controlled_env.py` 平台中立受控环境测试；第一轮 124、第二轮 131）。
5. 任务包 §6（`git diff --check`）：**exit 0**（无空白错误；含新增测试文件经 `add -N` 检查，三轮后仍 exit 0）。

### 13.5 正式 Postgres durable-fact 合同未被削弱的证据

- 产品 `provider_call_recorder.py` **未被修改**（`git diff` 无该文件本轮改动）；Postgres `SessionLocal`
  独立短事务行为完全不变。
- ADR 004 survive-rollback / ordinal / 价格绑定 / 删除级联由第 2 条命令（83 项，含
  `test_provider_call_survives_business_rollback`、`test_timeout_provider_call_survives_business_rollback`、
  `test_failed_provider_call_survives_business_rollback`、`test_rag_owner_provider_call_survives_business_rollback`
  与四链 Postgres orchestration）在**随机 throwaway Postgres** 上真实通过。
- legacy SQLite/eval 与正式 Postgres recorder 的明确行为差异：SQLite（StaticPool 单连接）只保证
  recorder“能跑、不锁”，提交在单连接上串行化；durable“跨业务 rollback 存活”的权威证据来自 Postgres
  路径，SQLite 仅作兼容回归。

### 13.6 约束确认

- **未进入 Batch B**，未进入 Stage 5 第三部分。
- 未修改 Web、Compose、CI、`tests/system/**`、`apps/mcp_execution/**` 或真实远程配置。
- 未调用真实 provider / Judge0 / Wolfram Cloud；未运行 OCR。
- 未安装依赖；未读取或修改 `.tmp/`、`artifacts/`。
- 未 `commit`、未 `push`。
- 未降低 Batch A 已有 124 项测试的断言（124/124 原样通过）；新增 `test_controlled_env.py`（8 项，平台中立）
  为 test-only，未触产品码（`controlled.py` 第三轮未改），不连任何远程服务。

完成后停止，交回 Codex 独立验收。
