# Stage 5 Part 2 Slice 2A：验收测试真实性修正包

状态：可执行

日期：2026-07-28

## 1. 目标

产品修正方向已基本通过，Codex 独立运行 Tutor 系统测试得到 `3 passed`。本轮只
替换四组不能证明产品行为的模拟测试，使测试真正经过被保护的 service/wrapper。

**本轮禁止修改任何产品代码。**

## 2. 允许修改

仅允许：

- `apps/api/tests/test_provider_call_recorder.py`
- `apps/api/tests/test_provider_call_chain_behavior.py`
- 必要时新增一个直接相关的测试文件；
- 更新 `PART_2_SLICE_2A_DURABLE_PROVIDER_CALL_GLM_HANDBACK.md`。

禁止修改：

- `apps/api/learn_platform_api/**`
- migration、ORM schema、Web、Compose、`tests/system/`、CI、Playwright；
- fixture 的全局产品语义和依赖；
- `.tmp/`、`artifacts/`。

不安装依赖，不调用真实 provider，不运行 OCR，不 commit，不 push。

## 3. RAG Trace：必须经过 `answer_question()`

替换当前手工创建 Trace、手工赋值并 commit 的两个测试。

新测试必须：

- 调用真实 `answer_question()`；
- 只在低层外部边界替换 retrieval、embedding/provider HTTP 等依赖；
- 成功路径让真实 service 创建并最终化 Trace；
- 失败路径让真实 provider helper 产生受控 timeout 或 provider failure；
- 调用结束后使用新的 Session 查询同一 Trace；
- 成功断言 `succeeded` 及必要 usage/completed_at；
- 失败断言 `failed`、稳定 error_code、completed_at；
- 同时查询该 Trace 的 Provider Call，确认 owner 与最终状态；
- 不直接给 Trace.status 赋值，不复制 `answer_question()` 实现。

## 4. Course 最小 owner：必须经过 `_execute_lesson_generation()`

替换当前在测试中手工重演创建 AgentRun、commit、创建授权、rollback 的测试。

新测试必须：

- 建立满足 science authorization 条件的真实最小 fixture；
- 调用真实 `_execute_lesson_generation()`；
- 只 monkeypatch capability projection、provider/network 等低层外部边界；
- 在首次 provider attempt 处制造受控失败，使业务 Session rollback；
- 使用新 Session 验证 AgentRun owner 已持久化；
- 验证本次新建的 JobToolAuthorization 没有被 owner commit 顺带持久化；
- 设置一个反例：若授权创建顺序重新移动到 owner commit 前，测试应失败；
- 不在测试中复制产品的提交顺序。

若该私有 service 难以直接构造，可经过更高层 `execute_generation()`，但不得降级
为手工模拟。

## 5. Start/FK 失败：必须经过 `record_provider_call()`

替换直接调用 `ProviderCallRecorder.start()` 且没有使用 `fake_call` 的测试。

新测试必须：

- 调用真实 `record_provider_call(..., call_fn=fake_call)`；
- 使用不存在的 AgentRun/RagAnswerTrace，或真实 workspace/owner FK 错绑；
- 让独立 recorder Session 在 started flush/commit 时触发真实数据库约束失败；
- 断言异常向上传播；
- 断言 `fake_call` 调用数严格为 0；
- 至少一项使用隔离 Postgres 验证正式复合 FK；SQLite 可作为快速补充；
- 不通过非法 phase 替代数据库失败。

非法 phase 测试可以保留，但名称必须明确它只验证输入校验。

## 6. Wrapper 最终化缺失：必须经过 `record_provider_call()`

替换直接调用 `recorder.succeed()/fail()` 的所谓 wrapper 测试。

### Provider 成功、最终化缺失

- 调用真实 `record_provider_call()`；
- `call_fn` 执行时，从另一 Session 删除 wrapper 刚创建的 Provider Call，然后
  返回成功结果；
- wrapper 在 `succeed()` 时真实遇到记录缺失；
- 断言 wrapper 不返回 provider 成功结果；
- 断言稳定的 finalization failure 及因果链。

### Provider 失败、失败最终化也缺失

- 调用真实 `record_provider_call()`；
- `call_fn` 删除已创建 Provider Call 后抛出已知 provider/业务异常；
- wrapper 的失败 finalizer 真实遇到记录缺失；
- 断言调用者接收到原始 provider/业务异常；
- 断言因果链中保留 finalization failure；
- 不 monkeypatch finalizer 直接抛出任意异常。

测试可在 `call_fn` 中按 owner 查询最新 `started` Provider Call 并通过独立
Session 删除，从而制造真实记录缺失。

## 7. 删除旧的无效证据

不得只新增正确测试而保留以下测试继续冒充证据：

- 手工修改并 commit RAG Trace；
- 手工复制 Course owner/authorization 顺序；
- 定义但从未传给 wrapper 的 `fake_call`；
- 名称声称测试 wrapper、实际只调用 finalizer。

可保留确有独立价值的 finalizer 单元测试，但必须改成准确名称和说明。

## 8. 验证

先运行四组新增测试，再运行：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_provider_call_chain_behavior.py
git diff --check
```

本轮不需要再次运行 Docker 系统测试，除非测试调整暴露产品行为冲突。不得把上轮
系统测试结果写成本轮新执行结果。

## 9. 交回

更新原 handback，逐项列出：

- 被删除或重写的无效测试；
- 每个新测试实际经过的产品入口；
- monkeypatch 只发生在哪个低层外部边界；
- 真实执行命令和结果；
- 产品代码零修改确认；
- 未 commit、未 push、未运行 OCR 的确认。

完成后停止，不进入 Slice 2B。
