# Slice 1B-3 Codex 独立验收

状态：通过

日期：2026-07-27

## 范围

验收安全 Provider Call 列表/详情 API、Workspace 隔离、owner/filter 合同、
Decimal/unknown 成本投影、响应白名单和查询边界。

## 独立检查

确认：

- 列表和详情查询首先限定 `ProviderCall.workspace_id`；
- owner filter 不会扩大 Workspace 范围；
- 详情对不存在和跨 Workspace 使用统一 404；
- 响应使用显式 Pydantic 白名单；
- 成本只读取调用绑定的价格快照并复用 `calculate_cost`；
- calculated 金额固定八位小数字符串；
- unknown 与真实零成本分离；
- 列表以 join eager load 避免价格快照 N+1；
- 未修改 AgentRunDetail，未新增 migration、Web、聚合或写入行为。

## 独立复验

Codex 实际运行：

```text
apps/api/tests/test_provider_call_read_api.py

27 passed in 56.05s
```

`git diff --check` 通过。GLM 另报告 `test_agent_run_api.py` 24 项回归通过；
Codex 未重复运行，以控制重复成本。

## 结论

Slice 1B-3 通过独立验收。1B-1/1B-2/1B-3 的实现仍未 commit、未 push。
按已接受策略，下一步是对三个小切片统一制作白名单副本并执行分块 OCR；在用户
批准真实付费 OCR 前只允许 preview、范围和 provider 安全预检。
