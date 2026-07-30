# Stage 5 Part 2 Slice 2A OCR 修正任务包

## 1. 目标

关闭 Slice 2A 分块 OCR 中确认的六项高置信测试与 CI 问题。

本任务只允许修改测试、stub、Playwright 和测试脚本。产品代码、公开合同、
schema、migration、Provider Call 语义及业务 orchestration 均不得修改。

完成本任务后停止，不进入 Slice 2B，不运行 OCR，不 commit，不 push。

## 2. 必须读取

- `AGENTS.md`
- `docs/README.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/README.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/006-controlled-system-tests-and-ci-gates.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/adr/003-controlled-test-boundaries-and-ci-gate-separation.md`
- `docs/05-platform-stage-5-observability-system-validation-and-quality/adr/004-durable-provider-call-facts-across-business-rollback.md`
- 本任务包

开始前运行 `git status --short --branch`，不得回滚或覆盖既有 dirty files。
不得读取或修改 `.tmp/`、`artifacts/`。

## 3. 允许修改的文件

- `scripts/browser-test.sh`
- `tests/system/model_services_stub/server.py`
- `tests/system/test_tutor_vertical.py`
- `apps/api/tests/test_four_chain_orchestration_postgres.py`
- `apps/api/tests/test_provider_call_recorder.py`
- `apps/web/e2e/app-shell.spec.ts`
- 本任务的 handback 文档

除非验证证明任务包事实错误，否则不得修改其他文件。发生冲突时停止并报告。

## 4. 必须修复

### Fix 1：Linux 浏览器脚本必须从仓库根目录清理

`scripts/browser-test.sh` 当前执行 `cd apps/web` 后没有恢复目录，导致 EXIT trap
从 `apps/web` 查找根目录 Compose 文件。

将 Playwright 命令放入子 shell，或采用等价方式保证父 shell 工作目录不变。
不得删除现有 cleanup trap，不得弱化非零退出传播。

### Fix 2：stub 场景读取与计数递增必须原子化

`tests/system/model_services_stub/server.py` 当前先读取 `ACTIVE_SCENARIO`，释放锁后
再通过 `_next_call()` 重新加锁递增计数。

把“读取当前场景 + 递增该场景计数”置于同一个 `LOCK` 临界区。`/__reset` 仍须在
同一把锁内切换场景并清零计数。不得改变 success、repair、timeout、failure 的响应合同。

### Fix 3：Tutor repair 必须产生可用回答

在 `test_tutor_invalid_answer_uses_bounded_repair` 中，除 `status == "succeeded"` 外，
增加 `answer_blocks` 非空断言。保留精确 Provider Call phase 和 ordinal 断言。

### Fix 4：四链 provider failure 必须匹配稳定错误

找到四链 Postgres 测试中裸 `pytest.raises(ValueError)` 的 Course provider failure
场景，为其增加准确 `match`，锁定产品当前实际抛出的稳定错误码。

不得为满足测试修改产品错误行为；如果当前错误码与既有 focused tests 或 Spec 冲突，
停止并报告。

### Fix 5：未来价格快照测试不得依赖固定日历日期

将 `test_provider_call_recorder.py` 中用于“未来价格快照”的硬编码
`2027-01-01` 改为相对当前 UTC 时间的未来日期，例如当前时间加 365 天。

使用模块级正常 import，不在测试函数内部临时 import。保持测试仍能证明未来快照
不会被当前 Provider Call 绑定。

### Fix 6：Playwright 失败诊断与 dialog Promise

在 `apps/web/e2e/app-shell.spec.ts`：

- 为 `courseResponse.ok()` 断言添加与 Reader 断言同等级的诊断，至少包含 HTTP status
  和响应正文。
- dialog handler 使用 async callback 并等待 `dialog.accept()`。
- 不降低 Tutor 回答、终态和运行记录断言。
- 不增加固定 sleep；继续使用可观察状态或真实响应等待。

## 5. 明确不采纳的 OCR 评论

不得顺手处理以下项目：

- 不降级 GitHub Actions 的 v6 action；OCR 使用了过时版本知识。
- 不删除或重命名 `scripts/system-test.sh`。
- 不为测试容器凭据引入 GitHub Secrets。
- 不修改 Course/Practice/Tutor/RAG 的产品 commit 合同。
- 不重构 `_test_session_factory`、Recorder ordinal 分配或业务 session fixture。
- 不清理无关 unused imports、重复历史测试、N+1 或 Java harness。
- 不新增 provider failure 系统场景；它是 Slice 2B 的候选输入。
- 不增加新的依赖。

## 6. 验证

先运行窄检查：

```powershell
docker build --target test -f apps/api/Dockerfile -t ha-stage5-2a-test .
docker run --rm --network host `
  -e TEST_POSTGRES_ADMIN_URL=postgresql://hello_agents:hello_agents@host.docker.internal:55432/postgres `
  -e TEST_POSTGRES_URL_TEMPLATE=postgresql+psycopg://hello_agents:hello_agents@host.docker.internal:55432/{name} `
  ha-stage5-2a-test `
  python -m pytest -q `
  tests/test_provider_call_recorder.py `
  tests/test_four_chain_orchestration_postgres.py
```

如果仓库现有测试使用固定 `localhost:55432` 而不读取上述环境变量，则使用此前已经
通过的、与本机 Docker/Postgres 相匹配的既有命令；不得修改产品代码绕过环境差异。

随后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\system-test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\browser-test.ps1
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ..\..
git diff --check
```

系统测试必须保持 Tutor success、repair、timeout 全部通过；Playwright 必须完成真实
Tutor 用户流程并看到成功运行记录。任何环境不可用必须明确失败，不得 skip 或写成通过。

## 7. Handback

生成：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2A_OCR_FIX_GLM_HANDBACK.md`

报告：

- 六项修复逐项对应的文件与行为；
- 实际运行的命令及结果；
- 未运行项及具体原因；
- 产品代码零修改证明；
- 未 commit、未 push、未运行 OCR、未进入 Slice 2B。
