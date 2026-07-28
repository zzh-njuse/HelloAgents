# Stage 5 Part 1 Slice 1C GLM 实现任务包

状态：可执行

日期：2026-07-28

## 1. Goal

一次性实现已接受的 Spec 005：新增 Workspace 级运行健康与人民币计算成本聚合
API，并在现有“运行记录”页面增加“质量与成本”Tab。实现必须支持从聚合发现
问题，再下钻到既有安全 Agent Run 和 Provider Call 事实。

本任务包不再拆分 API/Web 小 Slice。完成 API、Web、focused tests、构建和
handback 后停止，不进入 Stage 5 第二部分。

## 2. 仓库与运行环境

- 仓库：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`
- 当前分支：开始时以 `git status --short --branch` 的真实结果为准。
- Shell：Windows PowerShell。
- API Python：仓库 `.venv\Scripts\python.exe`。
- Web：`apps/web`，使用 `npm.cmd`。
- 产品事实数据库：Postgres。percentile 和聚合合同必须以真实隔离 Postgres
  验证，不能让 SQLite fixture 反向定义生产查询。
- 不读取、输出或提交 `.env`、API key、provider URL、真实 prompt、用户资料、
  `.tmp/` 或 `artifacts/`。
- 工作区可能存在用户/Codex 未提交改动；不得回滚、覆盖、stash 或清理未知改动。

不得安装或升级依赖，不得 commit/push，不得运行真实 provider、OCR 或浏览器
人工 smoke。

## 3. 开始前必须完整读取

仓库级：

- `AGENTS.md`
- `docs/README.md`
- `docs/LEARNING_AGENT_BLUEPRINT.md`
- `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
- `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
- `docs/AGENT_COLLABORATION_PLAYBOOK.md`
- `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`

Stage 5 与已接受合同：

- `docs/05-platform-stage-5-observability-system-validation-and-quality/README.md`
- `PART_1_CANDIDATE_SLICE_PLAN.md`
- `PART_1_SLICE_1A_FRONTEND_CONCEPT.md`
- `PART_1_SLICE_1C_FRONTEND_CONCEPT.md`
- `specs/001-complete-safe-run-summary-contract.md`
- `specs/002-provider-call-cost-foundation.md`
- `specs/003-provider-call-business-instrumentation.md`
- `specs/004-safe-provider-call-read-api.md`
- `specs/005-workspace-quality-cost-read-experience.md`
- `adr/001-provider-call-and-cny-cost-facts.md`
- `adr/002-provider-call-recording-lifecycle-and-rag-owner.md`
- `reviews/SLICE_1B_OCR_REVIEW.md`

然后读取相邻实现和测试，至少包括：

- Agent Run router/schema/service/tests；
- Provider Call router/schema/read service/cost calculator/tests；
- `db/models.py` 中 AgentRun、ProviderCall 和 owner 模型；
- `apps/web/src/app/AgentRunsPanel.tsx`、`App.tsx`、相邻 CSS；
- `apps/web/src/lib/api.ts` 和现有组件测试/前端测试能力。

若实际代码与已接受 Spec 冲突，停止冲突部分并在 handback 报告，不自行改变合同。

## 4. 允许修改范围

API 可新增或修改：

- `apps/api/learn_platform_api/routers/` 下质量成本只读 router；
- `apps/api/learn_platform_api/schemas/` 下白名单响应 schema；
- `apps/api/learn_platform_api/services/` 下聚合 read service；
- router 注册；
- focused API/Postgres tests。

Web 可新增或修改：

- `apps/web/src/app/AgentRunsPanel.tsx`；
- 必要的同目录质量成本组件；
- `apps/web/src/lib/api.ts`；
- 既有相关样式文件；
- 仓库已有前端测试体系内的 focused tests。

文档只新增 handback。不要顺手格式化或重构无关模块。

禁止：

- ORM/schema/migration、物化视图、缓存或后台 job；
- provider 写入、价格选择和成本事实合同；
- RAG/workspace-only Provider Call 聚合；
- prompt、回答、答案、日志或 raw response；
- 顶级导航、趋势图、饼图、provider/model 排行；
- 价格管理、预算、账单、导出或业务写操作；
- 生成、评分、重试预算、队列或状态机修改。

## 5. API 实现合同

严格实现：

```text
GET /api/v1/workspaces/{workspace_id}/quality-cost-summary
```

参数、枚举、白名单、排序、金额格式和错误语义以 Spec 005 为准。

实现要求：

1. 所有查询先绑定 `workspace_id` 和服务端计算的时间窗口。
2. business type 必须复用 Slice 1A owner/identity 规则；应抽取或复用最小共享
   投影，不复制一套可能漂移的业务猜测。
3. Provider/成本只聚合筛选后 AgentRun owner 的 Provider Calls。
4. 成本 unknown 优先级和 Decimal/ROUND_HALF_UP/八位精度与
   `provider_cost.py` 保持一致；禁止 float 和当前价格回填。
5. percentile 使用 Postgres 确定性聚合，仅统计合法终态 duration；空样本为
   null。
6. 使用有界数量的 SQL 聚合查询，禁止先加载窗口内全部 Run/Call ORM 行再用
   Python 循环聚合，禁止逐 Run N+1。
7. `runs_without_provider_calls` 使用数据库侧 existence/count 语义，不能把
   unknown cost 混入。
8. 响应不得包含 ID 列表、rate/snapshot、异常正文或其他高基数内部事实。
9. 不修改现有 Agent Run/Provider Call API 响应。

如果为复用 identity 需要对现有 `agent_runs` service 做窄小重构，必须保持
Slice 1A HTTP 回归不变，并在 handback 单独说明。

## 6. Web 实现合同

严格落地已接受的 `PART_1_SLICE_1C_FRONTEND_CONCEPT.md`：

- 现有“运行记录”页面内增加两个可访问 Tab，默认仍为“运行记录”；
- 质量与成本使用固定时间 segmented control，以及业务类型/角色/状态 select；
- 使用全宽 band/无框网格，避免卡片墙和卡片嵌套；
- 使用 lucide 图标完成刷新、下钻和关闭等明确命令；
- 显示运行健康、Provider usage、已知金额、unknown 和无计费事实；
- 失败分类使用紧凑列表/水平条，不使用饼图；
- 最近异常运行尽量复用现有 Run 行/详情，不复制一套漂移的 role、identity 和
  错误文案；
- Provider Call 下钻使用 Slice 1B API，不嵌入或扩大 AgentRunDetail；
- 摘要与异常列表允许独立失败；成功区域不能因另一请求失败被清空；
- 覆盖 loading、全空、无失败、部分/全部成本未知、无 Provider Call、无
  duration、未知枚举和详情错误；
- 桌面、中等和移动视口无重叠、无横向滚动、无字体随视口缩放；
- 不默认轮询，不修改业务状态。

界面文案不能把成功运行称为“回答正确”，不能把计算成本称为账单，也不能把
`0 + unknown` 显示为“总成本 0 元”。

## 7. 必须新增的测试

### API/Postgres

至少覆盖 Spec 005 第 8 节全部项目，并特别锁定：

- 默认/三个窗口的实际 `from/to` 边界；
- 组合筛选同时约束 Run 和其 Provider Calls；
- 跨 Workspace 反例；
- 相同事实聚合后能由既有列表/详情 API 回读；
- duration percentile 的空、偶数、奇数样本；
- mixed calculated/zero/unknown cost；
- usage 单维缺失不被补零；
- repair 多 Call 都计数；
- RAG/workspace-only Call 排除；
- 无 Call Run 与 unknown-cost Call 分离；
- 查询数量有界；
- 禁止敏感字段。

真实 percentile 和 SQL 行为必须在 throwaway Postgres database 验证，测试后
删除临时库，不触碰开发库。测试不得连接真实 provider。

### Web

在仓库现有测试能力允许的范围覆盖：

- API 类型和 query serialization；
- Tab 默认值与键盘/ARIA；
- 筛选变化；
- known/unknown/no-call 三种成本语义；
- loading/empty/error/partial failure；
- error category 和 Provider Call 下钻；
- 未知 role/error 安全文案。

若仓库没有可用的组件测试 runner，不得临时引入依赖；以 TypeScript、lint、
build 加 Codex/人工浏览器 smoke 作为分层验证，并在 handback 如实说明缺口。

## 8. 验证命令

先运行最窄 focused tests，再运行相关回归。以仓库真实测试文件名替换候选名，
handback 必须记录完整命令和结果：

```powershell
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_quality_cost_summary_api.py
.\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py apps/api/tests/test_provider_call_read_api.py
Push-Location apps/web
npm.cmd run lint
npm.cmd run build
Pop-Location
git diff --check
git status --short --branch
```

若 Postgres 测试拆为独立文件，也必须执行。任何缺少环境或失败项应原样报告，
不得写成“视为通过”。

## 9. 完成报告

新增：

`docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_SLICE_1C_GLM_HANDBACK.md`

至少包含：

- 修改文件与责任；
- API 查询数量和聚合方法；
- identity 复用方式；
- percentile、Decimal、unknown 和无 Call 的实现语义；
- Web 信息架构、状态和下钻实现；
- 新增测试矩阵与逐命令结果；
- 未运行的浏览器人工 smoke、真实 provider 和 OCR；
- 未解决问题、性能假设和需要 Codex 复核的风险；
- 明确确认未修改 migration、写入链、价格、业务状态或下一部分。

完成后保留工作区改动，不 commit、不 push、不运行 OCR，不进入 Stage 5 第二部分。
