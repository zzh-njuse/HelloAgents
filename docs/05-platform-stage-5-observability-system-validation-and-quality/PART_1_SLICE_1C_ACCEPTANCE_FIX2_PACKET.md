# Stage 5 Part 1 Slice 1C 第二轮验收修正包

状态：可执行

日期：2026-07-28

## 1. 结论

第一轮五项修正尚未全部关闭。只修复以下静态复核已确认的问题，不进行其他重构
或功能扩展。

## 2. 非 Postgres 不得返回伪事实

当前非 Postgres 分支返回：

- 有 duration 样本但 P50/P95 为 null；
- 有 calculated 调用但 `known_amount="0.00000000"`。

这会把“不支持计算”伪装为合法 API 事实，也保留了修正包明确禁止的双重产品
语义。

修复要求：

- 质量成本 endpoint/service 只支持 Postgres 产品路径；
- 非 Postgres 调用应稳定、明确失败，不返回部分伪摘要；
- 将 SQLite endpoint 测试迁移到隔离 Postgres，或把纯枚举/schema 测试与真实
  endpoint 行为分开；
- 删除非 Postgres percentile/cost 降级分支；
- handback 不再把 SQLite 38 passed 当作完整 HTTP 行为证明。

## 3. 空白 provider/model 必须与计算器一致

当前 SQL 只把 `NULL` 和 `""` 识别为 missing，但 `calculate_cost` 将空白字符
字符串也识别为 missing。

修复要求：

- SQL 使用 Postgres trim/btrim 后判空；
- provider/model 的 `NULL`、空串、空格/制表类空白均按既有计算器合同分类；
- 增加 Postgres 对照测试，证明 SQL unknown reason 与 `calculate_cost` 一致；
- 不修改 `provider_cost.py` 既有合同。

## 4. Identity 共享定义必须真正被使用

当前 `agent_runs.py` 虽然导入 `OWNER_KIND_PRECEDENCE` 并生成
`_OWNER_KIND_MAP`，但 `_OWNER_KIND_MAP` 从未使用，四个分支仍硬编码 kind。
此外通用 Agent Run service 反向依赖 Slice 1C 聚合模块，所有 Agent Run API
导入时都会加载质量成本实现。

修复要求：

- 把 owner-kind precedence 移到中性的最小模块，例如
  `services/agent_run_identity.py`；
- Agent Run `_identity()` 的 kind 赋值和质量成本 SQL CASE 都真正读取该共享
  定义；
- 删除未使用 map 和 `agent_runs -> quality_cost` 依赖；
- 测试不能只比较一份常量与自身，必须通过公开 Agent Run identity 和聚合
  business type 的真实结果做对照。

## 5. 异常列表补齐 business type

当前异常列表仅按 role/status 请求并按 summary 时间过滤，完全没有使用
`filterBusinessType`。因此选择“练习/代码执行”等业务类型后，摘要与异常列表
仍可能展示不同业务。

修复要求：

- 使用 Run 响应中的安全 `identity.kind` 在客户端过滤最近异常列表；
- 过滤值与质量摘要的五种 business type 完全一致；
- `unknown` 只匹配安全 kind=`unknown`；
- `filterBusinessType` 必须进入 callback 依赖；
- 继续保持列表有界，并在界面/handback 明确这是“最近异常”而非完整结果集。

## 6. Tab roving focus 必须移动焦点

当前 Arrow/Home/End 只修改 `activeTab`，浏览器焦点仍留在旧的
`tabIndex=-1` 元素，不满足 roving focus。

修复要求：

- 为两个 tab 使用 ref 或等价稳定机制；
- Arrow/Home/End 同时激活并聚焦目标 tab；
- 点击行为、默认“运行记录”和 ARIA 关联保持不变；
- 不安装测试依赖；Web build/lint 后把键盘路径列入浏览器 smoke。

## 7. 验证

必须运行并如实报告：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_postgres.py
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py apps/api/tests/test_provider_call_read_api.py
Push-Location apps/web
npm.cmd run lint
npm.cmd run build
Pop-Location
git diff --check
```

若保留 `test_quality_cost_summary_api.py`，其中 endpoint 行为必须使用 Postgres，
不能依赖返回伪事实的 SQLite 分支。

更新原 `PART_1_SLICE_1C_GLM_HANDBACK.md`，明确第二轮修正和实际测试分层。

完成后停止。不 commit、不 push、不运行 OCR、不进入 Stage 5 第二部分。
