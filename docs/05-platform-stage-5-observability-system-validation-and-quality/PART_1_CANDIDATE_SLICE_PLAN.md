# Stage 5 第一部分候选 Slice 计划：可观测与成本

状态：候选拆分；Slice 1A 已于 2026-07-27 完成，Slice 1B/1C 未批准

日期：2026-07-27

## 1. 拆分原则

第一部分不作为一个大 Slice 实现。建议按三个独立风险轴推进：

```text
Slice 1A 运行摘要合同补全
  -> Slice 1B Provider Call 与人民币成本事实
  -> Slice 1C 质量与成本读取体验
```

每个 Slice 分别完成 Spec、必要 ADR、实现任务包、focused verification、独立
验收和人工 Gate。前一 Slice 只提供后一 Slice 可依赖的事实，不提前建设完整
dashboard。

## 2. Slice 1A：运行摘要合同补全

### 目标

让现有 Run Trace 正确识别并安全展示 Stage 3/4 已经存在的全部运行角色和 owner，
先关闭“数据库事实已扩展、API/Web 仍停留在 Stage 3”的投影漂移。

### 候选范围

- 明确七种现有 Agent role 的公开枚举、中文标签和稳定筛选。
- 补全 Course、Tutor、Practice、Code Lab 的安全业务 identity。
- API/Web 对 role、kind、status 和 error code 使用一致合同。
- 保留 token 未报告、运行中 duration 和已删除对象的诚实语义。
- 为七角色列表、详情、筛选、Workspace 隔离和 Web 渲染建立矩阵测试。

### 明确不做

- 不新增 provider call 或 cost schema。
- 不计算人民币金额。
- 不建设聚合 dashboard。
- 不修改 Stage 4 Practice、评分、MCP 或执行行为。

### 候选 Gate

- 七角色均可正确列出、筛选和展示身份。
- 未知新角色不会空白或误显示为 Tutor。
- API/Web 不新增敏感字段；现有禁止字段负面测试继续通过。
- 当前业务主路径无行为变化。

### 风险等级

候选 L2：公开 API/Web 行为修复，但原则上不需要 migration。仍需先有小 Spec 和
前端状态矩阵。

## 3. Slice 1B：Provider Call 与人民币成本事实

### 目标

为每次真实 provider 调用建立可审计、可归因、可删除的最小事实，并在完整证据
存在时计算人民币成本。

### 候选范围

- 定义 provider call 与 Agent step、Tool call 的区别。
- 为调用记录 run owner、ordinal、phase、provider/model、status、latency、
  input/output usage、稳定错误和完成时间。
- 统一 Course、Tutor、Practice 和 RAG Answer 的 usage 缺失语义。
- 定义人民币 input/output 单价版本和“计算成本”规则。
- 缺 usage、provider/model 或单价时记录成本未知及稳定原因。
- 定义失败、取消、repair、显式 retry、Workspace 删除和 Tutor Turn 删除语义。
- focused tests 覆盖成功、partial usage、超时、取消、repair、retry 和历史价格
  不被当前配置改写。

### 明确不做

- 不建设多币种、实时汇率、折扣、套餐或账单系统。
- 不估算 embedding、Wolfram 或 self-host Code Lab 金额。
- 不保存 prompt、message、evidence、response、Tool 原始输入输出或 provider
  原始错误。
- 不把 AgentToolCall 当作 provider call 复用。
- 不默认运行真实付费 provider。

### 必要 ADR

本 Slice 涉及 schema、migration、金额事实、删除和保留，属于 L3。ADR 至少决定：

- 独立 provider call 表还是 AgentRun 扩展；
- 不可变 provider/model/rate snapshot；
- partial usage 与“可能已计费但未知”的表达；
- 历史数据兼容和删除权威；
- 金额精度、舍入位置和 API 投影。

### 候选 Gate

- 一个 attempt 内计划、生成、repair 和 retry 的调用事实不会互相覆盖。
- 完整 usage + 完整人民币单价才能产生金额。
- 任何缺失都显示 unknown，不用 0 或当前配置反推。
- 现有 Run/Tool 安全投影和业务事务权威不被破坏。

## 4. Slice 1C：质量与成本读取体验

### 目标

基于 1A/1B 已接受事实提供安静、可扫描的 Workspace 级质量与成本视图，帮助定位
Tutor、练习和编程链路问题。

### 候选范围

- Workspace 级时间范围、角色、状态和业务类型筛选。
- 成功/失败/取消分布、稳定错误分类、P50/P95 duration、provider call 数、
  input/output token 和人民币计算成本。
- 明确区分已知金额、成本未知和无外部计费事实。
- 从聚合结果下钻到现有安全 Run/Tool/provider call 摘要。
- 为后续 eval/系统测试保留安全关联位置，但不在本 Slice 重建 eval 平台。
- 桌面和移动视口的空、加载、错误、部分数据和长标签状态矩阵。

### 明确不做

- 不提供日志、prompt、原文或 raw response 查看器。
- 不提供账单、充值、预算扣款或套餐余额。
- 不建设跨 Workspace 排名或多租户运营后台。
- 不在读取页面修改价格、重试任务或改变业务状态。

### 候选 Gate

- 聚合值可以回读到权威 Run/provider call 事实。
- `unknown` 不进入已知金额合计，也不会显示为 0 元。
- 失败分类与下钻记录一致。
- 页面不因长角色名、错误标签或移动视口发生重叠。

### 风险等级

候选 L2；若新增持久化聚合、物化视图或保留策略，则升级为 L3 并补 ADR。

## 5. 与第二部分的边界

第一部分负责“记录并读取真实运行事实”。第二部分负责“用 CI 和系统测试持续
制造可重复证据”。Slice 1A/1B 的 focused tests 可以验证自身合同，但不得借此
宣称跨 Web、API、worker、数据库和外部 adapter 的系统测试体系已经完成。

## 6. 建议执行顺序

建议先评审 Slice 1A。原因：

- 已确认存在用户可见的投影漂移；
- 范围窄，不需要 migration；
- 能先让现有 Run Trace 正确覆盖 Stage 4 事实；
- 可作为 1B/1C 的公开枚举、identity 和安全投影基础。

Slice 1A 已通过人工 Gate，可以生成实现任务包。Slice 1B 的 schema/金额 ADR
可做预研，但不能提前 migration 或写入历史金额。

Slice 1A 评审入口：

- [Spec 001：完整且安全的运行摘要合同](specs/001-complete-safe-run-summary-contract.md)
- [Slice 1A 前端概念与状态矩阵](PART_1_SLICE_1A_FRONTEND_CONCEPT.md)
