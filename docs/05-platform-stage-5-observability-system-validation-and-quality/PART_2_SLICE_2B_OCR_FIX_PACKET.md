# Stage 5 Part 2 Slice 2B OCR 验收修正任务包

状态：已获人工授权，可交给 GLM 实现
日期：2026-07-30

## 1. 目标

只关闭 Slice 2B 统一 OCR 中经 Codex 结合代码与实跑事实确认的高可信问题：

1. 质量报告不得把“必需工具未调用”或“禁止工具被调用”记成成功；
2. 安全快照必须使用真正的显式字段白名单，并完整脱敏带空格或 `/` 的绝对路径；
3. 预算曲线不得保留比较两个无关 `Settings()` 对象的假阳性测试；
4. 受控执行后端的场景选择与计数必须原子一致；
5. provider stub 不得通过重复最后一个响应掩盖超额调用；
6. Tutor 的授权状态、异步状态和幂等键必须在失败与 capability 变化时保持可恢复；
7. 浏览器删除确认必须成为真实断言，不能留下跨迭代的 `dialog` listener。

本任务不重新设计产品，不改变 Spec 006/007、Provider Call、Practice artifact、MCP
协议、工具预算或远程 Gate 标准。

## 2. 开始前必须读取

完整读取：

- 根 `AGENTS.md`
- `docs/README.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
- 当前 Stage README
- `specs/006-controlled-system-tests-and-ci-gates.md`
- `specs/007-high-risk-tool-and-practice-quality-baseline.md`
- `adr/003-controlled-test-boundaries-and-ci-gate-separation.md`
- `PART_2_SLICE_2B_BATCH_A_GLM_HANDBACK.md`
- `PART_2_SLICE_2B_BATCH_B_GLM_HANDBACK.md`

然后检查 `git status --short --branch`。当前工作树包含 Slice 2A/2B 大量未提交改动；
不得回滚、覆盖、清理或格式化未知改动，不得读取 `.tmp/`、`artifacts/`、`.env`、
真实 provider 配置或用户上传资料。

## 3. 允许修改的文件

只允许按需要修改：

- `apps/api/tests/quality_baseline/report.py`
- `apps/api/tests/quality_baseline/controlled.py`
- `apps/api/tests/quality_baseline/test_report_contract.py`
- `apps/api/tests/quality_baseline/test_budget_curve.py`
- `apps/api/tests/quality_baseline/test_controlled_env.py`
- `tests/system/fake_execution_backend/server.py`
- `tests/system/model_services_stub/server.py`
- `tests/system/test_practice_vertical.py`
- `tests/system/test_tutor_tools_vertical.py`
- `apps/web/src/app/TutorPanel.tsx`
- `apps/web/e2e/app-shell.spec.ts`
- `apps/web/e2e/practice-tools.spec.ts`
- 本 handback 文档

如确实需要在同目录新增一个极小 focused test 文件，先在 handback 说明理由；不得修改
schema、migration、API route、worker、Practice/Tutor 生成策略、Compose、CI、依赖或
远程配置。发现修复必须越界时停止并报告。

## 4. 必须修复

### Fix 1：科学工具分类必须覆盖合同违例

`classify_science_tool_run()` 至少锁定：

- `expectation=required` 且 `called=false`：
  - 未请求仍为 `tool_request_missed`；
  - 已请求但未调用使用稳定失败类别，例如 `tool_call_missed`，不得返回
    `succeeded_without_wolfram`；
- `expectation=forbidden` 且 `called=true`：返回稳定合同违例类别，例如
  `forbidden_tool_called`，不得进入成功分类；
- authorization、capability、schema、connection、invalid result、reference
  verification 和 artifact publication 的既有优先级不得漂移。

新增表驱动测试覆盖所有分支和优先级，至少包含 required/optional/forbidden 的调用与
未调用反例。

### Fix 2：显式快照白名单与绝对路径脱敏

- `ALLOWED_SNAPSHOT_KEYS` 必须是人工维护的显式不可变字段集合，不得由
  `dataclasses.fields()`、`asdict()` 或实例字段自动生成；
- 测试证明给 `RunRecord` 临时或未来增加敏感字段时不会自动进入序列化白名单；
- `_ABS_PATH_RE` 或等价实现必须完整遮蔽：
  - 含空格的 Windows 路径；
  - Windows `/` 和 `\` 两种分隔形式；
  - 含空格的 POSIX 路径；
- 不得把普通诊断文本整段误删；现有长度上限和 `<path>` 输出合同保持不变。

### Fix 3：预算设置测试必须观察真实执行对象

删除或重写 `test_budget_curve.py` 中比较独立 `Settings()` 默认实例的假阳性断言。

测试必须捕获并断言实际传入 `execute_generation()` 的 settings 对象在执行前后关键预算
字段未被修改。不得仅比较两个新构造的默认对象，也不得降低 1/3/5/10 总题数矩阵、
最终题数、step count 或失败分类断言。

### Fix 4：fake execution 场景与计数原子一致

参照 model-services stub 已采用的模式：

- 在同一 `LOCK` 临界区读取 `ACTIVE_SCENARIO` 并递增该场景计数；
- helper 返回 `(scenario, ordinal/count)`；
- `/submissions` 后续行为只使用该次原子快照，不能再次读取全局场景；
- 新增并发/交错 reset 反例，证明一次请求不会被计入 A 却按 B 返回；
- 既有 reset、call counter、Accepted/compile/runtime/timeout/infra failure 合同不变。

不要借机重写 HTTP server 或真实 Judge0 adapter。

### Fix 5：provider stub 超额调用必须显式失败

当 `ordinal > len(SCENARIO_RESPONSES[scenario])` 时，不得继续重复最后一个响应。

要求：

- 返回稳定、可诊断且不含 prompt/secret 的 HTTP 错误；
- 不让 client 无响应或挂起；
- focused test 证明正常序列不变，首次超额调用明确失败；
- 现有 Slice 2A success/repair/timeout/failure 和 Slice 2B 八类场景合同不变；
- 系统测试中 provider 调用次数仍使用精确断言。

### Fix 6：Tutor 授权、异步状态和幂等键可恢复

在 `TutorPanel.tsx` 内窄修：

1. capability 从 ready 变为 unavailable 时，对应
   `scienceToolAuthorized` / `codeToolAuthorized` 自动变为 `false`，避免
   disabled-but-checked；
2. `refreshSessions()` 与学习记忆/完成记录加载必须防止旧 workspace、旧课程或卸载后的
   请求写回新状态；使用现有 abort、sequence 或 cancelled 模式，不引入依赖环；
3. `createTutorTurn()` 成功后立即消费/清理该次 idempotency key，再请求 session；
   - 若创建失败，保留 key 以便同一次用户操作安全重试；
   - 若创建成功但随后的读取失败，下次用户提交不得复用已消费 key；
4. 不破坏 Slice 2B 已通过的 EventSource + 2.5 秒有界轮询方案，不改变 120 秒上界。

Web 无测试运行器时，不安装依赖。至少以 lint、build 和现有 9 条浏览器 Gate 验证。

### Fix 7：浏览器确认对话框必须被证明

- `app-shell.spec.ts` 的确认操作必须等待并断言 dialog 确实出现；
- `practice-tools.spec.ts` 循环删除每个 Set 时，使用与 click 同步的
  `waitForEvent("dialog")` 或等价有界模式；
- dialog handler 不得残留到下一次循环或下一项操作；
- 不添加固定 sleep，不通过 API 直接删除，不降低真实 UI 删除与最终状态断言；
- `tutor-tools.spec.ts` 无需因为 OCR 关于 listener 注册时机的猜测而修改，除非可用实际
  浏览器反例证明 `fill()` 会触发该确认框。

### Fix 8：小型测试资源真实性修正

- `test_practice_vertical.py` 中临时 `httpx.Client` 必须使用 context manager 或 fixture
  关闭；
- Tutor Wolfram negative 在调用前显式断言计数基线为 0，再断言调用后仍为 0；
- 不把精确 stub token usage 改成 `> 0`；这些值是 Provider Call 事实合同，不是 tokenizer
  推测；
- 不删除 fake counter isolation 反例，只可在 handback 说明其层级。

## 5. 明确拒绝或暂缓的 OCR 评论

不得实现以下 OCR 建议：

- 不降级 `actions/checkout@v6`、`setup-node@v6`、`setup-python@v6` 或
  `upload-artifact@v5`；这些版本真实存在，OCR 使用了过期知识；
- 不删除 Compose `!reset` / `!override`；当前 Docker Compose 已真实解析、构建并通过
  system/browser Gate；
- 不把 CI 临时 Postgres 密码迁入 secret；它是隔离服务的非生产固定凭据；
- 不修改 4 维 Qdrant seed；`compose.system-test.yml` 明确设置
  `PRODUCT_EMBEDDING_DIMENSION=4`；
- 不修改 `seed_browser_tutor.py` 的导入；浏览器 Gate 已真实运行；
- 不新增 uvicorn 依赖；fake Wolfram 镜像已经真实构建和启动；
- 不处理嵌套 ternary、颜色、Safari 前缀、CSS 类命名、timeout 常量、未使用 import 等
  Low/nit；
- 不改 `package-lock.json`；OCR 未审该生成文件，`npm ci`、lint、build 是其验证边界；
- 不增加真实 provider、Judge0 或 Wolfram 调用，不开始 Remote Gate。

## 6. 必须新增或更新的测试

最低需要：

1. science classifier 全分支表驱动测试；
2. 显式白名单未来字段反例与三类绝对路径脱敏测试；
3. 实际 settings 对象不变性测试；
4. fake execution reset 竞态反例；
5. provider stub 正常边界与首次超额调用失败测试；
6. dialog 必须出现且 listener 不跨迭代残留的浏览器行为；
7. Tutor capability 失效、成功创建后读取失败的手工 smoke 步骤写入 handback。

不得以源码字符串检查替代行为测试。

## 7. 验证

先运行最窄 focused tests，再运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/quality_baseline
.\scripts\system-test.ps1
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
.\scripts\browser-test.ps1
git diff --check
```

要求：

- quality baseline：0 failed、0 skipped；
- system Gate：11 passed、0 failed、0 skipped；
- browser Gate：9 passed、0 failed、0 skipped；
- lint 0 errors；build 成功；
- Compose 测试容器、网络、卷全部清理；
- 不把此前 GLM 或 OCR 报告冒充本轮实跑结果。

若某项失败，定位根因并在允许范围内修复；需要越界时停止报告。

## 8. Handback

生成：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_2_SLICE_2B_OCR_FIX_GLM_HANDBACK.md`

必须包含：

- 实际修改文件；
- Fix 1–8 逐项结果；
- 新增测试与每条验证命令的独立结果；
- 未采纳 OCR 评论及理由；
- 未解决问题和是否需要 Codex 裁定；
- `remote_not_run`；
- 明确声明未 commit、未 push、未运行 OCR、未进入真实远程 Gate或第三部分。

完成后停止，交回 Codex 独立验收。
