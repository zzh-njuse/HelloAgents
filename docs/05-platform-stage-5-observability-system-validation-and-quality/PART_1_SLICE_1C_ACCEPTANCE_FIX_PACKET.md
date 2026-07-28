# Stage 5 Part 1 Slice 1C 独立验收修正包

状态：可执行

日期：2026-07-28

## 1. 结论

Slice 1C 候选实现暂不接受。不要扩大功能范围；只关闭以下五个已复现的合同
阻断项，然后更新原 handback。

本修正包不改变 Spec 005 或前端概念，不新增 migration、依赖或公开管理能力。

## 2. Fix 1：数据库侧 percentile

当前 `services/quality_cost.py` 把窗口内全部 duration 行加载到 Python，并使用
nearest-rank。它同时违反：

- Spec 005 “Postgres percentile、结果取整”；
- 不把窗口内全部事实加载进应用内存；
- nearest-rank 与 `percentile_cont` 在偶数样本上并不等价。

修复要求：

- 在 Postgres SQL 中计算合法终态 duration 的 sample count、P50 和 P95；
- 使用 `percentile_cont(...).within_group(...)` 或等价确定性 Postgres 表达式；
- 连续 percentile 结果按 Spec 取整为毫秒；
- 空样本返回 null；
- 删除 Python duration 行加载、`math`、nearest-rank helper 和不实注释；
- 新增隔离 Postgres 测试，使用能区分 nearest-rank 与 continuous percentile 的
  偶数样本锁定确切结果。

不得保留“生产 SQL、SQLite 另一套算法”的双重产品语义。SQLite 可测试枚举和
schema，但不能冒充 percentile 验收。

## 3. Fix 2：数据库侧成本聚合

当前实现把窗口内所有 Provider Call 和 rate 行加载到 Python 循环调用
`calculate_cost`。这违反 Spec 005 和任务包的有界聚合要求；“单条查询”不等于
“有界结果集”。

修复要求：

- 使用数据库聚合表达式直接得到 known amount、calculated count、unknown count
  和四种 unknown reason count；
- Decimal/Numeric、1e6 除数、ROUND_HALF_UP 和八位输出必须与
  `provider_cost.py` 合同一致；
- unknown 优先级严格保持
  `provider_missing > model_missing > usage_missing > rate_missing`；
- 真实零成本属于 calculated；
- 删除 `cost_rows` 全量加载和 Python per-call 循环；
- Postgres 测试逐项比较明细 API/`calculate_cost` 与聚合结果，包括混合、
  零成本、部分 usage 和每种 unknown reason。

不要为此修改 Provider Call、价格快照或成本计算器的既有事实合同。

## 4. Fix 3：真实 Postgres 与查询边界测试

当前 38 项测试全部使用 SQLite；handback 也明确承认没有运行隔离 Postgres。
因此不能证明本 Slice 的核心生产查询。

修复要求：

- 增加独立 Postgres focused test 文件或等价隔离 fixture；
- 使用 throwaway database，测试后删除，不触碰开发库；
- 至少覆盖 percentile、成本 SQL、组合筛选、Workspace 隔离、RAG/workspace-only
  排除和 `runs_without_provider_calls`；
- 增加查询数量断言；
- 增加防回归断言，证明 endpoint 不执行返回每条 duration/cost 事实的全量查询；
- handback 分开报告 SQLite HTTP 合同测试和 Postgres 聚合事实测试。

如果本机 Postgres 不可达，必须停止并如实报告，不能再次写成完成。

## 5. Fix 4：Identity 单一映射

当前 `_business_type_case()` 手写了一份与 `_identity()` “保持同步”的 CASE，
handback 却称“未复制一套可能漂移的猜测”，两者矛盾。

修复要求：

- 抽取一个最小共享 identity kind/owner precedence 定义，让 Agent Run 安全投影
  与质量聚合共同依赖；
- 不改变 Slice 1A 的公开 identity 文案或 owner 降级；
- 为五种 kind 和 owner 优先级增加漂移回归测试；
- 若 SQL 与 Python 不能直接共用表达式，至少共享单一 owner precedence 常量/
  builder，并以 HTTP 对照测试锁定两侧一致，不能只写“必须保持同步”的注释。

## 6. Fix 5：Web 筛选、Tab 与移动下钻

当前 Web 有以下合同偏差：

1. “最近异常运行”始终请求 failed+canceled，忽略 `window`、
   `business_type` 和用户选择的 `status`，造成摘要与列表口径不一致。
2. Tab 的 `aria-labelledby` 指向不存在的 ID，也没有已接受概念要求的键盘
   Arrow/Home/End 行为。
3. Provider Call table 在移动端没有有界滚动或响应式替代，可能制造页面横向
   overflow。
4. 异常 Run 直接显示 `identity.kind` 英文值，没有复用 Slice 1A 的安全中文
   identity/role 文案。
5. 全部成本未知时仍突出显示 `¥0.00000000`，与“暂无可计算金额”语义同时出现。

修复要求：

- 异常列表必须与当前窗口、role、business type 和 status 语义一致：
  - status 为空时显示 failed+canceled；
  - status=failed/canceled 时只显示对应异常；
  - status=started/succeeded 时显示“当前筛选不包含异常运行”，不得偷偷请求另一
    状态；
  - 复用返回的安全 identity 对业务类型过滤，并按 summary `from/to` 限定窗口；
  - 请求保持有界，并在 handback 说明“最近列表”而非完整聚合。
- 为两个 tab 增加稳定 ID、正确关联、roving focus 和 Arrow/Home/End 键盘操作。
- Provider Call 表格放入自身横向滚动容器或移动端可扫描布局，页面根不能横向
  滚动。
- 复用/抽取 Slice 1A role 和 identity label helper，不显示原始英文 kind。
- 当 `calculated_call_count=0` 且存在 unknown/no-call 时，主金额显示“暂无可计算
  金额”；只有存在 calculated 事实时才突出人民币已知金额。
- `QualityCostQuery.status` 使用独立的
  `started | succeeded | failed | canceled` 类型，不通过 cast 冒充 Slice 1A
  公共 `AgentRunStatus`（其进行中值为 `running`）。
- 失败分类补充一个可访问的“查看近期异常”动作，滚动/聚焦到异常列表即可，
  不新增 error_code API。

仓库没有组件测试 runner时不要安装依赖。必须运行 lint/build，并由 handback
列出需要 Codex/人工浏览器 smoke 的桌面、移动、键盘和部分失败路径。

## 7. 验证

至少运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_api.py
.\.venv\Scripts\python.exe -m pytest -q <新增 Postgres 聚合测试文件>
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py apps/api/tests/test_provider_call_read_api.py
Push-Location apps/web
npm.cmd run lint
npm.cmd run build
Pop-Location
git diff --check
```

更新：

`PART_1_SLICE_1C_GLM_HANDBACK.md`

必须纠正“6 个查询”实际列出 7 个、nearest-rank 等同 percentile_cont，以及未
复制 identity 规则等不准确表述。

完成后停止。不 commit、不 push、不运行 OCR、不进入 Stage 5 第二部分。
