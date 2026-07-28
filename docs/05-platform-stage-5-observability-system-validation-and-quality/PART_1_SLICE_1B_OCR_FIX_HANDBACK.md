# Stage 5 Part 1 Slice 1B：OCR 修复 Handback

日期：2026-07-28

## 1. 修改文件

### 业务代码

| 文件 | 修改内容 |
|---|---|
| `apps/api/learn_platform_api/services/answers.py` | `_generate`：`except (KeyError, TypeError, …)` → `except (IndexError, KeyError, TypeError, …)` |
| `apps/api/learn_platform_api/services/course_generation.py` | `call_provider`：`except (httpx.HTTPError, KeyError, TypeError, …)` → `except (httpx.HTTPError, IndexError, KeyError, TypeError, …)` |
| `apps/api/learn_platform_api/services/practice_generation.py` | `call_provider` 和 `call_practice_provider`：同上，各加 `IndexError` |
| `apps/api/learn_platform_api/services/provider_call_recorder.py` | `ProviderCallRecorder.timeout()`：新增 `self._call.error_code = PROVIDER_TIMEOUT` |

### 测试文件

| 文件 | 修改内容 |
|---|---|
| `apps/api/tests/test_provider_call_recorder.py` | 更新 `test_recorder_timeout` 和 `test_record_provider_call_timeout` 断言 `error_code == PROVIDER_TIMEOUT`；新增 7 个测试（Fix 1 四链空 choices、Fix 2 三项 timeout 稳定码） |
| `apps/api/tests/test_provider_call_chain_behavior.py` | 5 处 timeout 断言追加 `error_code == PROVIDER_TIMEOUT`；新增 4 个测试（Fix 1 四链空 choices 通过真实 helper） |
| `apps/api/tests/test_provider_call_read_api.py` | 新增 3 个测试（Fix 3：同 started_at id DESC 排序、started 状态 completed_at=null、started 状态完整 usage 计算成本） |

## 2. 三项修复行为摘要

### 修复一：空 choices 的稳定错误

**问题**：当 provider 返回 HTTP 200 + 合法 JSON 但 `choices=[]` 时，`choices[0]` 触发 `IndexError`。此异常不在各 helper 的 `except` 元组中，导致：
- RAG Answer `_generate`：`IndexError` 穿透到 `httpx.HTTPError` catch，被映射为 `ValueError("generation_provider_unavailable")` 而非 `ValueError("invalid_model_output")`
- Course/Practice `call_provider` / `call_practice_provider`：`IndexError` 完全未被捕获，以原始 `IndexError` 传播

**修复**：在四个 helper 的 `except` 元组中添加 `IndexError`，使其被映射到各自既有的稳定错误合同：
- RAG Answer → `ValueError("invalid_model_output")`
- Course → `ValueError("generation_provider_unavailable")`
- Practice `call_provider` → `ValueError("provider_unavailable")`
- Practice `call_practice_provider` → `ValueError("provider_unavailable")`

Tutor 复用 Course `call_provider`，无需额外修改。

### 修复二：timeout 稳定错误码

**问题**：`ProviderCallRecorder.timeout()` 只写入 `status = timed_out`，不写入 `error_code`，导致 timeout 事实缺少稳定错误码。

**修复**：在 `timeout()` 方法中固定写入 `self._call.error_code = PROVIDER_TIMEOUT`（即 `"provider_timeout"`）。该值由 recorder 集中控制，不接受调用方传入任意正文。

### 修复三：读取 API 边界测试

**问题**：缺少对以下两场景的 API 测试覆盖：
1. 两条 Provider Call 使用相同 `started_at` 时，列表按 `id DESC` 稳定排序
2. `status=started` 的调用返回 `completed_at=null`，其他白名单字段正常，若 usage 与绑定价格完整则成本仍按事实计算

**修复**：仅补测试，不改变已接受 API。新增三个测试覆盖上述场景。

## 3. 新增/修改测试

### test_provider_call_recorder.py（+7 新增，2 修改）

修改：
- `test_recorder_timeout`：断言 `error_code == PROVIDER_TIMEOUT`
- `test_record_provider_call_timeout`：断言 `error_code == PROVIDER_TIMEOUT`（原断言 `is None`）

新增：
- `test_record_provider_call_empty_choices_rag_answer`：RAG Answer `_generate` + `choices=[]` → `invalid_model_output`
- `test_record_provider_call_empty_choices_course`：Course `call_provider` + `choices=[]` → `generation_provider_unavailable`
- `test_record_provider_call_empty_choices_practice`：Practice `call_provider` + `choices=[]` → `provider_unavailable`
- `test_record_provider_call_empty_choices_practice_generation`：Practice `call_practice_provider` + `choices=[]` → `provider_unavailable`
- `test_record_provider_call_timeout_has_stable_error_code`：直接 `httpx.TimeoutException` → `status=timed_out, error_code=provider_timeout`
- `test_record_provider_call_chained_timeout_has_stable_error_code`：`ValueError` 包装 `httpx.TimeoutException` → 同上
- `test_non_timeout_failure_not_misclassified`：`httpx.ConnectError` → `status=failed`，不被误分类为 `timed_out`

### test_provider_call_chain_behavior.py（+4 新增，5 修改）

修改：5 处 timeout 断言追加 `error_code == PROVIDER_TIMEOUT`

新增：
- `test_rag_answer_empty_choices_via_real_helper`：通过真实 `_generate` + monkeypatched `httpx.post` 验证
- `test_course_generation_empty_choices_via_real_helper`：通过真实 `call_provider` 验证
- `test_practice_call_provider_empty_choices_via_real_helper`：通过真实 Practice `call_provider` 验证
- `test_practice_call_practice_provider_empty_choices_via_real_helper`：通过真实 `call_practice_provider` 验证

### test_provider_call_read_api.py（+3 新增，1 验收修正）

- `test_same_started_at_sorts_by_id_desc`：两条相同 `started_at` → `id DESC` 稳定排序（验收修正：使用 `sorted([id1, id2], reverse=True)` 计算期望序，不假设随机 UUID 创建顺序）
- `test_started_status_has_completed_at_null`：`status=started` → `completed_at=null`，白名单字段正常，无 usage → `usage_missing`
- `test_started_status_with_complete_usage_calculates_cost`：`status=started` + 完整 usage + 绑定价格 → 成本按事实计算

## 4. 实际运行命令和结果

### 初次运行（三项修复后）

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_provider_call_chain_behavior.py `
  apps/api/tests/test_provider_call_read_api.py
```

结果：**112 passed in 264.07s**

### 验收修正后运行

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_read_api.py `
  -k "same_started_at or started_status"
```

结果：**3 passed in 8.67s**

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_read_api.py
```

结果：**30 passed in 89.13s**

```powershell
git diff --check
```

结果：仅有 CRLF 行尾警告（Windows 正常），无空白错误。

## 5. 未运行项

- 全量 API 测试套件
- Web build
- 真实 provider 调用
- OCR
- Docker compose

## 6. 确认未触碰暂缓项

以下暂缓项均未触碰：

- `_next_ordinal` 并发锁和完整 orchestration 系统测试
- CORS、认证、多租户或部署安全
- prompt injection 关键词过滤
- DocumentChunk、既有时间戳默认值或其他旧模型
- Course/Tutor/Practice 的既有 lease、version、MCP 或科学工具问题
- Pydantic 额外 root validator、服务层重复 limit
- 测试数据库配置、全仓测试卫生和无关重构
- relationship loading strategy 变更
- Web、聚合、价格管理或新 migration
- 业务调用次数、prompt、重试、事务、API 合同

## 7. 确认未 commit、未 push、未运行 OCR

- 未执行 `git commit` 或 `git push`
- 未运行 `ocr review` 或 `ocr scan`
- 所有改动保留在工作区
