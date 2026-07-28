# Spec 005：Workspace 质量与成本读取体验

状态：已接受（2026-07-28）

日期：2026-07-28

适用范围：Platform Stage 5 第一部分 Slice 1C

## 1. 目标

基于 Slice 1A 的安全 Agent Run 摘要和 Slice 1B 的 Provider Call/CNY 成本事实，
提供一个安静、可扫描的 Workspace 级只读诊断入口。维护者应能先发现失败集中、
延迟异常或成本未知，再下钻到既有 Run 和 Provider Call 事实。

本 Slice 观察的是运行健康与计算成本，不把运行成功率命名为回答质量，不创建
主观质量分数。Tutor、普通练习和编程练习的内容质量基线属于 Stage 5 第二部分
eval/系统测试。

## 2. 权威事实与范围

- 运行数量、状态、role、duration 和错误码来自 `AgentRun`。
- Provider 调用数、usage、状态和价格绑定来自 `ProviderCall`。
- 人民币金额只使用调用绑定的 `ProviderRateSnapshot`。
- 业务类型使用 Slice 1A 的安全 identity 投影：
  `course_generation | tutor | practice | code_execution | unknown`。
- Provider 指标只聚合拥有 `agent_run_id` 的调用，使筛选和下钻具有同一 Run
  归因。RAG Answer owner 和 workspace-only owner 继续由 Slice 1B 独立读取 API
  查看，不混入本页合计。
- Code Lab/Wolfram 等无 Provider Call 的 self-host 运行不显示为零元；它们属于
  “无外部计费事实”。

不得从当前 provider 设置反推历史价格，不得读取 prompt、答案、用户输入、
evidence、raw response 或异常正文。

## 3. 聚合 API

新增：

```text
GET /api/v1/workspaces/{workspace_id}/quality-cost-summary
```

查询参数：

```text
window          24h | 7d | 30d，默认 24h
role            可选，七种已知 Agent Run role
status          可选，started | succeeded | failed | canceled
business_type   可选，五种安全 identity kind
```

未知枚举返回 422。Workspace 不存在或正在删除时沿用 `workspace_is_active` 返回
404。时间窗口以服务端当前 UTC 为上界，采用 `[now-window, now]`，响应返回实际
`from`/`to` ISO 时间，便于核对。

响应白名单：

```text
window
from
to
filters.role
filters.status
filters.business_type

runs.total
runs.by_status.started
runs.by_status.succeeded
runs.by_status.failed
runs.by_status.canceled
runs.duration_ms.p50
runs.duration_ms.p95
runs.duration_ms.sample_count
runs.errors[]                 { error_code, count }

provider_calls.total
provider_calls.by_status[]    { status, count }
provider_calls.input_tokens
provider_calls.output_tokens
provider_calls.usage_complete_count
provider_calls.usage_unknown_count

cost.currency                 CNY
cost.known_amount
cost.calculated_call_count
cost.unknown_call_count
cost.unknown_by_reason[]      { reason, count }
cost.runs_without_provider_calls
```

金额是固定八位小数的字符串。无已知金额时 `known_amount` 仍返回
`"0.00000000"`，但必须同时依靠 `calculated_call_count`、
`unknown_call_count` 和 `runs_without_provider_calls` 表达事实，界面不得把它
解释为“全部免费”。

`errors` 只包含非空稳定错误码，按 `count DESC, error_code ASC` 排序。
Provider Call 状态和 unknown reason 使用公开稳定枚举，不增加异常正文兜底。

## 4. 筛选与归因

所有筛选先作用于当前 Workspace 和窗口内的 Agent Run：

- `role` 匹配 `AgentRun.role`；
- `status` 匹配 `AgentRun.status`；
- `business_type` 复用 Slice 1A identity owner 链规则，不创建第二套猜测逻辑；
- Provider Call 与成本指标只统计筛选后 Run 所拥有的调用；
- `runs_without_provider_calls` 统计筛选后没有任何 Provider Call 的 Run；
- 一个 Run 的 repair/retry 调用分别计数，不覆盖、不去重。

未知历史 role 不进入已知 role 筛选，但在无 role 筛选的总数中保留，并由
`business_type=unknown` 安全归类。已删除 owner 的既存安全降级语义保持不变。

## 5. 聚合规则

- duration percentile 只使用非空且非负的终态 `duration_ms`；
- 无 duration 样本时 P50/P95 为 `null`，不能写成 0；
- percentile 采用 Postgres 确定性 percentile 计算，结果取整为毫秒；
- token 合计只加总已报告的对应维度，同时返回完整/未知 usage 调用数；
- 成本完整性和 unknown reason 必须与 `calculate_cost` 合同一致；
- unknown 调用不进入 `known_amount`；
- 真实零成本属于 calculated；
- failed、timed_out、canceled 调用仍按实际 usage 和绑定快照计算；
- 聚合查询不得修改或补写任何 Run、Provider Call 或价格快照。

本 Slice 不新增表、migration、物化视图、缓存或后台聚合作业。聚合在 Postgres
读取时完成，不把窗口内全部 ORM 行加载进应用内存。若真实规模验证表明该方案
不可接受，应停止并单独评审持久化聚合 ADR。

## 6. Web 入口与下钻

在现有 Workspace“运行记录”页面增加“质量与成本”Tab，不新增顶级导航。

- “运行记录”保持 Slice 1A 行为；
- “质量与成本”显示本 Spec 聚合；
- 最近异常运行继续复用现有 Agent Run 列表 API；
- 点击运行进入/展开既有安全 Run 详情；
- Provider Call 下钻调用 Slice 1B 独立列表 API，不扩大 AgentRunDetail；
- 页面只读，不提供价格管理、重试、取消、删除或业务状态修改。

具体信息层级、状态和响应式要求见
`PART_1_SLICE_1C_FRONTEND_CONCEPT.md`。

## 7. 性能与安全

- 聚合必须始终带 `workspace_id` 和时间下界；
- 最大窗口固定为 30 天，不接受任意起止时间；
- 不返回跨 Workspace 数量、排名或全局统计；
- 不返回 provider rate、snapshot ID 或高基数原始标签；
- 不按 model、provider、Run ID 或任意错误文本生成聚合维度；
- API 一次请求使用有界查询数量，避免逐 Run/逐Call N+1；
- 现有索引不足时不得在本 Slice 偷加 migration；先用真实查询计划证明，再进入
  独立 Gate。

## 8. 最低验证

通过公开 HTTP API 和真实 ORM/Postgres 行为覆盖：

- 三个时间窗口和默认值；
- role/status/business type 单项及组合筛选；
- Workspace 隔离、删除中 Workspace 和未知枚举；
- 四种 Run 状态、未知 role、空数据；
- duration 无样本、偶数/奇数样本和 P50/P95；
- Provider Call 状态、repair 多调用和 token 部分缺失；
- calculated、真实零成本、四种 unknown reason及其混合合计；
- 无 Provider Call 的 Run 与 unknown cost 明确分离；
- RAG/workspace-only Provider Call 不混入 Agent Run 聚合；
- 聚合结果可用既有 Run/Provider Call API 回读；
- 禁止字段不出现在响应；
- 查询数量有界，且不会把窗口内全部事实加载为 ORM 列表；
- Slice 1A、1B 读取 API focused regression；
- Web lint/build 和桌面、移动浏览器 smoke。

测试不得用源码字符串检查代替 HTTP/数据库行为，不调用真实 provider。

## 9. 明确不做

- 持久化聚合、物化视图、保留/降采样策略；
- 趋势预测、告警、SLO、跨 Workspace 排名；
- provider/model 维度排行；
- RAG Answer 独立质量或成本聚合；
- eval 平台、回答质量分数或学习效果指标；
- 价格设置、账单、充值、预算扣款、套餐、多币种或汇率；
- CSV/报表导出；
- prompt、回答、用户答案、日志或 raw response 查看器；
- 修改生成、评分、重试预算、队列或业务状态机。

## 10. 人工 Gate

1. 是否接受在现有“运行记录”页增加 Tab，而不是新增顶级导航？
2. 是否接受固定 `24h/7d/30d`，不提供任意日期范围？
3. 是否接受聚合只覆盖 AgentRun owner 的 Provider Call，RAG/workspace-only 调用
   继续通过独立 API 查看？
4. 是否接受“运行健康”与“内容质量”明确分离，不在 1C 创建质量分数？
5. 是否接受不新增 migration/缓存，先使用 Postgres 即时聚合？
6. 是否接受成本同时展示已知金额、未知调用数和无外部计费 Run 数？
7. 是否接受本 Slice 不提供 provider/model 排行、趋势图或价格管理？

以上七项已于 2026-07-28 通过人工 Gate。实现者不得自行扩大聚合 owner、时间
窗口、质量语义、导航或管理能力；发现代码事实冲突时停止对应部分并报告。
