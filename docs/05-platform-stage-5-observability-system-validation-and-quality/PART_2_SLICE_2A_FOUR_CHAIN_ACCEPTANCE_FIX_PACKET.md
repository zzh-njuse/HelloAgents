# Stage 5 Part 2 Slice 2A：四链 Orchestration 验收修正包

状态：可执行

日期：2026-07-29

## 1. 背景

四链 Postgres 测试已能经过真实 service 并写入 ProviderCall，但 Codex 独立审查
发现 normal/repair 测试会吞掉任意 orchestration 异常，并且没有锁定 provider
实际调用次数。因此产品链即使在生成 ProviderCall 后失败，测试仍可能通过。

本轮只修正
`apps/api/tests/test_four_chain_orchestration_postgres.py`，禁止修改产品代码。

## 2. 不得吞掉正常场景异常

Course generation、Practice generation、Practice grading 的 normal/repair 测试中，
删除以下模式：

```python
try:
    execute_...(...)
except Exception:
    db.rollback()
```

normal 和 repair 都必须由真实 orchestration 正常返回。任何异常都应直接使测试
失败，并显示真实 traceback。

RAG Answer 继续要求正常返回 `succeeded`。

## 3. 锁定业务最终状态

每条 normal/repair 测试从新 Postgres Session 查询并断言：

- AgentRun 或 RagAnswerTrace 为 `succeeded`；
- 对应 Job/Attempt/Trace 的既有成功状态没有退化；
- normal/repair 产生的业务 artifact 或 feedback 至少存在一项关键权威事实；
- 不只证明 ProviderCall 被写入。

如果当前 service 的职责是修改 ORM、由 worker 外层 commit，则测试应在 service
正常返回后按真实 worker 合同 commit，再使用新 Session 查询。不得通过手工写入
成功状态来代替 orchestration。

## 4. 精确调用次数与 phase

每个 normal/repair 测试必须同时断言：

- provider stub/mock 的实际 `call_count`；
- ProviderCall 精确数量；
- 两者完全相等；
- normal 的精确 phase 序列；
- repair 的精确 phase 序列；
- ordinal 精确为 `range(expected_count)`。

不得继续使用 `len(calls) >= N`。预期：

- Course：normal 2，repair 3；
- Practice generation：normal 2，repair 3；
- Practice grading：normal 1，repair 2；
- RAG Answer：normal 1，repair 2。

如果真实合同与这些数字不同，停止并报告，不自行放宽断言。

## 5. Postgres Gate 不得 import skip

删除模块级 `pytest.importorskip("psycopg")`。

本文件是明确的 Postgres Gate：

- `psycopg` 缺失应以正常 ImportError/明确 RuntimeError 失败；
- Postgres 不可达继续明确失败；
- 不允许 skip 或 SQLite fallback；
- 随机 throwaway database 和 finally 清理保持不变。

## 6. 避免重复和虚假声明

- owner 互斥测试可以保留，但不能用它替代四条链各自的 owner 断言；
- timeout 测试继续允许预期异常，但必须精确断言调用次数与一条 timeout
  ProviderCall；
- 文件头和 handback 不得声称未实际断言的调用次数或最终状态；
- 不新增近似重复测试，保持现有 11 项或更少。

## 7. 允许范围

仅允许修改：

- `apps/api/tests/test_four_chain_orchestration_postgres.py`
- Slice 2A handback

禁止修改产品代码、其他测试、fixture、Compose、CI、Playwright、Web、migration、
schema 和依赖。不得读取或修改 `.tmp/`、`artifacts/`。

不调用真实 provider，不运行 OCR，不 commit，不 push。

## 8. 验证

运行：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_four_chain_orchestration_postgres.py
git diff --check
```

若本地 `.venv` 不可执行，可使用现有 Docker test image，但必须运行这一个真实
Postgres Gate，并报告实际命令。不能只运行 SQLite focused tests。

## 9. 交回

更新 handback，列出：

- 删除了哪些异常吞噬；
- 四条链 normal/repair 的最终业务状态；
- 每个场景的精确 mock call count、ProviderCall count 和 phase；
- Postgres 缺失不再 skip；
- 实际命令与结果；
- 产品代码零修改确认。

完成后停止，不进入 Slice 2B。
