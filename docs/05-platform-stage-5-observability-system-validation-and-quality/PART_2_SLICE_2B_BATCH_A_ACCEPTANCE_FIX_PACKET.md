# Stage 5 Part 2 Slice 2B Batch A 验收修正任务包

## 1. 状态与目标

Batch A 候选实现已交回，但尚未通过 Codex 独立验收。本轮只关闭两个验收阻断项：

1. Slice 2A 独立 Provider Call recorder 使 Stage 4 offline eval / stability 回归失效；
2. C++ controlled compiler Gate 在 Codex 环境中无法复现通过，且当前诊断只报告退出码。

完成后停止并交回 Codex。不得进入 Batch B。

## 2. 必须读取

- `AGENTS.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/006-controlled-system-tests-and-ci-gates.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/007-high-risk-tool-and-practice-quality-baseline.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/adr/004-durable-provider-call-facts-across-business-rollback.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2B_GLM_IMPLEMENTATION_PACKET.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2B_BATCH_A_GLM_HANDBACK.md`
- 本任务包

开始前运行 `git status --short --branch`，保留全部既有改动。

## 3. 阻断项一：旧回归必须真实通过

### 3.1 已复现事实

任务包 §11 的既有回归未通过。GLM 报告为 SQLite `database is locked`；Codex 独立抽验还复现了
Stage 4 offline eval 内存 SQLite 会话与 recorder 默认 Postgres SessionFactory 混用，导致：

`provider_calls(agent_run_id, workspace_id)` 找不到对应 `agent_runs` 复合外键。

这不是 Batch A 新测试本身引入的，但它是当前 Slice 2A durable recorder 改动造成的真实回归，
不能以“既有测试”或“与 Batch A 无因果关系”为由接受。

### 3.2 修正要求

- 先证明每个失败实际使用的业务 Session 和 recorder Session 来自哪个 engine/database。
- 修复必须保持 ADR 004 的正式 Postgres 合同：Provider Call 在独立短事务中提交，业务回滚后仍存活。
- 不得让正式 Postgres 路径退回调用方 Session。
- 不得通过 skip、xfail、删除断言、吞异常、关闭 FK、禁用 recorder 或伪造 ProviderCall 解决。
- SQLite 只允许作为 legacy eval/test 兼容路径；若采用 backend-specific test/eval 适配，必须明确隔离，
  不得改变正式 Postgres 行为。
- 优先修改 eval/test fixture 或测试 runner；只有证明无法在测试边界正确表达 ADR 004 时，才允许对
  `provider_call_recorder.py` 做最小、显式按 dialect 隔离的兼容修正。
- 不得把 legacy eval 静默迁移成依赖开发数据库。若迁移到 Postgres，必须使用随机 throwaway database，
  不可达即 FAIL，并在 handback 说明为何仍可称 offline eval。

必须让下列命令零失败：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_stage4_eval.py `
  apps/api/tests/test_slice5_practice_stability.py `
  apps/api/tests/test_slice5_practice_worker.py `
  apps/api/tests/test_provider_call_chain_behavior.py
```

同时复跑 ADR 004 / orchestration 回归，证明没有牺牲 durable facts：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_acceptance_evidence_wrapper.py `
  apps/api/tests/test_acceptance_evidence_course_owner.py `
  apps/api/tests/test_acceptance_evidence_rag_trace.py `
  apps/api/tests/test_four_chain_orchestration_postgres.py
```

## 4. 阻断项二：C++ Gate 必须可诊断且可复现

Codex 抽验：

```text
g++: C:\msys64\ucrt64\bin\g++.exe
version: 16.1.0
trivial compile: exit 1
current diagnostic: only "g++ present but trivial compile failed rc=1"
```

修正要求：

- 独立复跑最小 C++ 编译预检和至少一个 C++ generation/harness 用例。
- 查明失败是环境、命令参数、编码、输出路径、运行库还是 test helper 缺陷。
- 预检失败信息必须包含经过脱敏、长度受限的稳定诊断，不能只给退出码；不得包含绝对路径。
- 不得 skip、xfail、改成 Python 代跑、返回假成功或移除真实 `g++` Gate。
- 若编译器环境确实不可用，本轮必须保持 FAIL，并准确报告缺失条件；不得宣称 Batch A 通过。

至少运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/quality_baseline/test_coding_baseline.py
```

## 5. 边界

- 不进入 Batch B。
- 不修改 Web、Compose、CI、`tests/system/**` 或真实远程服务配置。
- 不调用真实 provider、Judge0、Wolfram Cloud。
- 不安装依赖。
- 不读取或修改 `.tmp/`、`artifacts/`。
- 不运行 OCR。
- 不 commit，不 push。
- 不降低 Batch A 已有 124 项测试的断言。

## 6. 完成验证

除第 3、4 节命令外，还必须运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/quality_baseline/
git diff --check
```

不允许只报告分组相加结果；每条命令给出精确 passed/failed/skip 和耗时。

## 7. Handback

更新：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2B_BATCH_A_GLM_HANDBACK.md`

必须补充：

- 两个阻断项的真实根因；
- 修改文件和边界理由；
- legacy SQLite/eval 与正式 Postgres recorder 的明确行为差异；
- C++ 预检的脱敏诊断与实际编译器事实；
- 全部验证结果；
- 产品正式 Postgres durable-fact 合同未被削弱的证据；
- 未进入 Batch B、未运行远程服务/OCR、未 commit/push 的确认。
