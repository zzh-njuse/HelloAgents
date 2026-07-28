# Spec 004：安全 Provider Call 与人民币成本读取 API

状态：已接受（2026-07-27）

日期：2026-07-27

适用范围：Platform Stage 5 第一部分 Slice 1B-3

## 1. 目标

为 Workspace 维护者提供 Provider Call 的安全只读 API，使一次真实调用的 owner、
phase、状态、usage、延迟和人民币成本可以被核对。

本 Slice 只建立读取合同，不建设聚合 dashboard 或 Web。Workspace 级趋势、
P50/P95、成功率和质量/成本体验仍属于后续 Slice 1C。

## 2. API

新增：

```text
GET /api/v1/workspaces/{workspace_id}/provider-calls
GET /api/v1/workspaces/{workspace_id}/provider-calls/{provider_call_id}
```

列表支持：

- `agent_run_id`；
- `rag_answer_trace_id`；
- `status`；
- `phase`；
- `limit`，默认 20，范围 1..50。

`agent_run_id` 与 `rag_answer_trace_id` 不能同时提供。未知枚举返回 422；合法但属于
其他 Workspace 的 owner 不得泄漏记录。

列表按 `started_at DESC, id DESC` 稳定排序。owner 内调用顺序由响应中的 ordinal
表达；本 Slice 不增加 cursor、总数或任意时间范围查询。

详情只按 `workspace_id + provider_call_id` 读取，不属于该 Workspace、已删除或不
存在时统一返回 404。

## 3. 安全响应

列表和详情使用同一个最小白名单模型：

```text
id
owner.kind                    agent_run | rag_answer | workspace
owner.agent_run_id
owner.rag_answer_trace_id
ordinal
phase
provider
model
status                        started | succeeded | failed | timed_out | canceled
input_tokens
output_tokens
latency_ms
error_code
started_at
completed_at
cost.currency                 CNY
cost.status                   calculated | unknown
cost.amount                   decimal string | null
cost.unknown_reason           provider_missing | model_missing |
                              usage_missing | rate_missing | null
```

owner 字段必须与数据库 owner 事实一致，不能通过请求参数或当前业务状态猜测。

不得返回：

- prompt、message、question、answer、evidence、citation；
- provider 原始响应、异常正文、HTTP body 或 headers；
- API key、base URL、内部连接 URL；
- input hash、上传原文、文件路径；
- 价格快照 ID、原始费率或内部 ORM 对象；
- RagAnswerTrace 的 question/answer hash 或 evidence/citation IDs。

## 4. 成本投影

每条响应只使用 Provider Call 已绑定的价格快照和 Slice 1B-1
`calculate_cost` 计算，不读取当前配置或最新价格。

- 金额使用 Decimal；
- JSON `amount` 必须是固定八位小数的字符串；
- 完整事实产生 `status=calculated`；
- 真实零成本返回 `"0.00000000"`；
- 缺失事实产生 `status=unknown`、`amount=null` 和一个稳定 unknown reason；
- unknown 不得显示为 0；
- 失败、timeout、取消不自动代表 unknown，仍按实际 usage/快照计算；
- 不把派生成本回写数据库。

Provider Call 绑定价格快照但快照因异常数据不可读取时，安全降级为
`rate_missing`，不能回退到当前价格。

## 5. Workspace 隔离与查询

- 所有查询首先限定 `ProviderCall.workspace_id`；
- owner filter 不能绕过 Workspace 限定；
- Workspace 不存在或正在删除时沿用现有 `workspace_is_active` 语义返回 404；
- 不通过 owner join 扩大结果集；
- 只读 API 不创建价格、不修复历史调用、不改变业务状态。

实现应避免列表 N+1：一次查询加载计算所需的可选价格快照。不得为了避免 N+1
引入持久化聚合或物化视图。

## 6. 向后兼容

- 不修改 Slice 1A 的 Agent Run 列表/详情响应；
- 不把 Provider Calls 嵌入 AgentRunDetail，避免现有响应膨胀；
- 不修改 RAG Answer、Course、Tutor 或 Practice 公开响应；
- 不新增 migration；
- 不修改 Provider Call 写入、价格选择、业务调用次数或事务边界。

## 7. 最低验证

通过公开 HTTP API 和真实 ORM 行为覆盖：

- Workspace 列表与详情；
- AgentRun owner、RAG owner 和 Workspace-only owner；
- owner/status/phase/limit 过滤；
- 两个 owner filter 同时出现时 422；
- 跨 Workspace owner filter 不泄漏；
- 跨 Workspace/不存在详情统一 404；
- calculated、真实零成本和四种 unknown reason；
- 历史绑定价格不被后续快照改写；
- failed/timed_out/canceled 的成本只由事实决定；
- 列表稳定排序且无 N+1；
- 禁止字段不出现在序列化响应；
- Slice 1A Agent Run API 回归。

测试不得读取源码字符串代替 HTTP 行为；不得调用真实 provider。

## 8. 明确不做

- Web 页面或 dashboard；
- Workspace 聚合、趋势、percentile 或预算；
- 价格管理 API；
- Provider Call 删除/修改/retry；
- CSV/账单导出；
- 多币种和汇率；
- embedding、Wolfram 或 Code Lab 成本；
- 完整业务 orchestration 系统测试。该项已登记为 Stage 5 第二部分强制输入。

## 9. 验收与 OCR

- GLM 一次实现 API/schema/service/focused tests 并生成 handback；
- Codex 做安全投影、Workspace 隔离、Decimal/unknown 和查询边界的轻量验收；
- 1B-3 不单独执行 OCR；
- 1B-3 验收后，对 1B-1/1B-2/1B-3 统一制作白名单副本并分块 OCR。

2026-07-27 已接受独立列表/详情 API、固定八位小数字符串、unknown 与真实零
成本分离，以及不修改 AgentRunDetail、通过独立 endpoint 下钻。
