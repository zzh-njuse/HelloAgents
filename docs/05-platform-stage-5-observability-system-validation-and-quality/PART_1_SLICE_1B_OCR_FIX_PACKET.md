# Stage 5 Part 1 Slice 1B：OCR 修复任务包

状态：可执行
日期：2026-07-28

## 1. 背景

Slice 1B-1/1B-2/1B-3 已通过独立验收，统一 OCR 已完整扫描 24 个白名单文件。
本任务只处理人工分诊后采纳的三项直接问题，不重新打开 Slice 范围。

权威合同：

- [Spec 002](specs/002-provider-call-cost-foundation.md)
- [Spec 003](specs/003-provider-call-business-instrumentation.md)
- [Spec 004](specs/004-safe-provider-call-read-api.md)
- [ADR 001](adr/001-provider-call-and-cny-cost-facts.md)
- [ADR 002](adr/002-provider-call-recording-lifecycle-and-rag-owner.md)

## 2. 运行边界

- Windows PowerShell
- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- 使用仓库现有 `.venv`
- 当前 Slice 1B 全部改动仍是未提交合法基线，不得回滚或重建
- 不读取或改动 `.tmp/`、`artifacts/`
- 不安装依赖，不调用真实 provider
- 不运行 OCR，不 commit，不 push

开始前读取根 `AGENTS.md`、Playbook、GLM handoff workflow、本任务包及权威合同，
并检查 `git status --short --branch`。

## 3. 修复一：空 choices 的稳定错误

检查本 Slice 接入的 OpenAI-compatible provider response parser：

- `services/answers.py::_generate`
- `services/course_generation.py::call_provider`
- `services/practice_generation.py::call_provider`
- `services/practice_generation.py::call_practice_provider`

这些路径读取 `choices[0]`。当 provider 返回 `choices=[]` 时，必须捕获
`IndexError` 并映射到该 helper 既有的稳定错误合同：

- RAG Answer 保持 `ValueError("invalid_model_output")`；
- Course 保持 `ValueError("generation_provider_unavailable")`；
- Practice 两个 helper 保持各自既有 `ValueError("provider_unavailable")`。

不得更改正常响应解析、prompt、provider 请求、重试次数或公开错误合同。Tutor
复用 Course `call_provider`，不得为 Tutor 复制另一套修复。

新增 focused tests，必须让真实 helper 接收一个 HTTP 200、合法 JSON、但
`choices=[]` 的 provider stub，并证明：

- helper 抛出预期稳定 ValueError；
- 经 recorder 的 Provider Call 为 `failed`；
- `error_code` 是稳定码，不是 `IndexError` 正文；
- RAG Answer Trace 不遗留为 `running`。

## 4. 修复二：timeout 稳定错误码

Provider Call 的 timeout 最终状态必须同时包含：

```text
status = timed_out
error_code = provider_timeout
```

把该规则集中在共享 recorder，不在五条业务链重复设置。允许让
`ProviderCallRecorder.timeout()` 固定写入 `PROVIDER_TIMEOUT`，或采用等价的
集中实现；不得接受调用方传入任意 timeout 正文。

更新 recorder 和真实 helper timeout tests，证明：

- 直接和被 ValueError cause 包装的 `httpx.TimeoutException` 都产生上述事实；
- 原业务异常仍按既有合同重新抛出；
- 非 timeout HTTP/provider failure 仍为 `failed`，不能被误分类。

## 5. 修复三：读取 API 边界测试

只补测试，不改变已接受 API：

1. 两条 Provider Call 使用相同 `started_at`，验证列表按 `id DESC` 稳定排序；
2. `status=started` 的调用返回：
   - `completed_at=null`；
   - 其他白名单字段正常；
   - 若 usage 与绑定价格完整，成本仍按事实计算。

不要修改列表排序、响应字段、filter 或 AgentRunDetail。

## 6. 明确暂缓

不得处理以下 OCR 评论：

- `_next_ordinal` 并发锁和完整 orchestration 系统测试；
- CORS、认证、多租户或部署安全；
- prompt injection 关键词过滤；
- DocumentChunk、既有时间戳默认值或其他旧模型；
- Course/Tutor/Practice 的既有 lease、version、MCP 或科学工具问题；
- Pydantic 额外 root validator、服务层重复 limit；
- 测试数据库配置、全仓测试卫生和无关重构；
- relationship loading strategy 变更；
- 任何 Web、聚合、价格管理或新 migration。

这些内容或属于第二部分系统测试输入，或不在 Slice 1B 范围。

## 7. 最低验证

只运行直接相关检查：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_provider_call_recorder.py `
  apps/api/tests/test_provider_call_chain_behavior.py `
  apps/api/tests/test_provider_call_read_api.py
git diff --check
```

若新增测试放入更合适的既有业务 focused 文件，可追加该文件并在 handback 说明。
不运行全量 API、Web build、真实 provider 或 OCR。

## 8. 交回

生成 `PART_1_SLICE_1B_OCR_FIX_HANDBACK.md`，包含：

- 修改文件；
- 三项修复的行为摘要；
- 新增/修改测试；
- 实际运行命令和结果；
- 未运行项；
- 确认未触碰暂缓项；
- 确认未 commit、未 push、未运行 OCR。

完成后停止，不进入 Slice 1C。
