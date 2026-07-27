# Self-host 学习平台开发路线

版本日期：2026-07-27

状态：当前执行路线

## 1. 路线原则

- 使用 **Platform Stage** 表示新产品交付阶段。
- 2026 年 5 月已完成的能力演进保留为 **Legacy Phase 1-4**，不改写历史含义。
- 每个 Stage 先有 Spec；跨模块、数据库、删除、权限和部署决策先有 ADR。
- 每个 Stage 结束时保留验证结果、暂缓风险和下一阶段输入。
- 误仓库代码是参考实现，不自动成为当前 Stage 的实现。
- 八股/LeetCode 是 fixture，不是单独产品路线。

## 2. 当前状态

当前状态：**Platform Stage 4 Slice 1/2/3/4/5 已完成并于 2026-07-24 归档。
Platform Stage 5 顶层方向已通过人工 Gate，Slice 1A 已于 2026-07-27 完成实现、
独立验收、浏览器 smoke 和 OCR；Slice 1B/1C 尚未批准**。

已经完成：

- 0R 基线重建、Stage 1 self-host 平台壳、Stage 2 资料生命周期、Stage 3 章节与 Tutor，以及 Stage 4 练习、掌握度、Memory、教学 Skill、受控代码/Wolfram 工具和练习稳定化。
- Postgres 事实源、Qdrant 可重建索引、Redis 非权威队列的产品合同已落实。
- Stage 4 自动化、离线 eval、Web build、分块 OCR 和人工浏览器 smoke 已归档。

下一步：

- Stage 5 先建立最小观测事实和代表性系统测试，再根据证据优化 Tutor、练习、编程链路和课节交互。
- Stage 5 顶层输入和范围见 [Stage 5 文档入口](./05-platform-stage-5-observability-system-validation-and-quality/README.md)。

## 3. Platform Stage 0R：基线重建

### 目标

让正确仓库的文档、依赖、验证命令和 prototype contract 足以支持新的 Stage 1 设计。

### 范围

- 文档整理、现状评估和历史收敛。
- 明确 `hello_agents` / `academic_companion` / product app 三层边界。
- 区分缺依赖、环境问题和真实行为失败。
- 固化现有 API/Web/streaming 行为清单。
- 形成 Stage 1 spec/ADR 的输入。

### 非目标

- 不迁移误仓库业务代码。
- 不建立 Postgres schema、Compose 或最终 product app。
- 不修改 Agent 业务行为来追求测试全绿。

### 完成 Gate

- Stage 0R README、Spec、ADR 和本路线一致。
- 依赖/测试基线可复现。
- prototype contract inventory 完成。
- Stage 1 的目标、非目标、候选文件和验证命令明确。
- 人工批准进入 Stage 1。

## 4. Platform Stage 1：Self-host 最小产品壳

### 用户价值

用户可以按文档启动平台、打开 Web、检查系统状态并创建 workspace。平台能够通过一个最小 adapter 调用已有领域能力，证明产品层与能力层接通。

### 建议范围

- `apps/api`：FastAPI product app、配置、workspace API、readiness。
- `apps/web`：工作台、workspace 列表/创建、系统状态。
- Postgres + Alembic：只建立 Stage 1 必需 schema。
- Docker Compose：Postgres、Qdrant、Redis、API、Web。
- product/domain adapter：选择一个低风险能力接点。
- focused tests、Web build、Compose smoke 和阶段 review。

### 明确不做

- 文件上传和 ingestion worker。
- Course Reader、完整聊天迁移、练习与 memory 产品化。
- 多用户鉴权、Hosted SaaS、Neo4j。

### 关键决策

- 误仓库 `apps/*` 是逐文件移植还是按正确仓库重建。
- prototype `/api` 与 product `/api/v1` 的兼容策略。
- app 依赖、配置命名空间和 Docker build 边界。
- Stage 1 最小 adapter 的输入输出。

### 完成 Gate

- 干净环境按文档启动 Compose。
- Web 和 API 可访问，readiness 不泄露敏感信息。
- workspace CRUD 最小路径通过。
- migration 可重复执行。
- adapter smoke 通过，不绕过产品 API。

## 5. Platform Stage 2：资料生命周期与引用检索

### 用户价值

用户可以在 workspace 上传资料，查看处理状态，并对资料执行带引用检索。

### 建议范围

- document/version/chunk/job/citation 数据模型。
- local storage、Redis worker、embedding 和 Qdrant workspace filter。
- 失败状态、显式重试、软删除和索引重建。
- Ingestion Center、引用片段和资料问答页面。
- 离线 fixture tests 和显式真实 provider smoke。

### 两个交付切片

**切片 1：单文件资料管线**

- 支持单个 PDF、Markdown 或纯文本文件。
- 完成上传、异步解析、分块、Postgres 持久化、embedding 和 Qdrant 索引。
- `rag/query` 只返回检索结果与引用，不调用 LLM 生成答案。
- 建立最小 query trace 和 RAG eval。

**切片 2：批量上传与带引用答案**

- 增加批量上传；每个文件创建独立 document/version/job，可独立失败和重试。
- 在切片 1 稳定检索链路上增加带引用的 LLM 自然语言答案。
- 完成 Stage 2 Web 资料问答体验和引用定位。
- 在批量放大资料处理前建立 parser 隔离，以及页数、文本、chunk、token、时间和并发预算；超限不得静默截断后标记 ready。
- 本切片的回答是单轮受证据约束的生成服务，不引入 Tutor Agent、工具循环、memory 或聊天 session；这些合同留在 Stage 3。

### Stage 2 整体非目标

- 不生成章节化课程页、知识图谱或练习题。
- 不实现长期学习记忆、多用户鉴权或 Neo4j。
- 不把聊天框作为唯一产品入口。
- 不把 Qdrant 当作 chunk 正文或业务状态的唯一来源。
- 不为现有八股/LeetCode 设计专用模型。

Office、图片 OCR、网页/Git 导入和更广泛 parser 不属于已确认的两个核心切片，但不是永久排除项。核心切片稳定后，可通过新的 parser extension slice 和 ADR 决定放在 Stage 2 后续还是后续 Stage。

### 完成 Gate

- 一份小资料可从上传走到 ready。
- 批量上传时每个文件有独立状态和重试语义。
- Postgres、storage 和 Qdrant 职责符合 ADR。
- 删除后默认检索不再返回资料。
- 检索和自然语言答案的 citation 可定位到 document version 和 chunk。
- worker 失败可见、可重试。

## 6. Platform Stage 3：章节化学习与 Tutor

### 用户价值

用户可以把资料组织成章节，在 Course Reader 中阅读，并获得当前上下文内的带引用辅导。

### 建议范围

- course/section/lesson/version/citation。
- Course Architect 与 Lesson Writer 的受控生成。
- Course Reader 三栏核心体验。
- Tutor 绑定 workspace、section、citation 和最小 memory context。
- 第一个真正 Agent 上线时同步建立最小 run/tool trace，不把正确性审计推迟到 Stage 5。
- 生成内容发布状态与重生成。
- RAG/citation/lesson 最小 eval。

### 完成 Gate

- 章节内容可追溯、可版本化。
- Tutor 资料不足时不伪造引用。
- Course Reader 支持稳定重复学习操作。
- 固定 eval case 可重复运行。

## 7. Platform Stage 4：练习、记忆与复习闭环

方向上拆为四个顺序 Slice：练习/作答/反馈，掌握度/复习/Memory，教学 Skill 产品化，以及选定具体场景后的受控 MCP。各 Slice 仍需独立 Spec/ADR 和人工 Gate；MCP 当前仅保留代码执行沙箱、数学工具和日历同步候选，不提前锁定。

### 用户价值

用户作答后得到反馈，平台记录薄弱点并形成复习队列。

### 建议范围

- exercise/rubric/attempt/feedback。
- learning event、concept mastery、review item。
- Exercise Agent 和 Review Coach。
- memory 可查看、纠正和删除。
- 练习质量与掌握度更新 eval。

### 完成 Gate

- 作答、评分、反馈和复习形成可审计链路。
- memory 不以隐藏文件作为唯一事实来源。
- 用户可以理解系统为什么推荐某项复习。

## 8. Platform Stage 5：可观测、系统验证与质量优化

### 用户价值

平台运行质量、失败原因和成本可见；关键学习主路径能够被系统测试重复验证，
并据此改善 Tutor、练习、编程链路和课节交互。

### 建议范围

- 可观测与成本：统一安全的 run/tool/job/eval、失败分类、latency、usage 和成本口径。
- CI 与系统测试：建立跨 Web、API、worker、Postgres 和必要 adapter 的代表性纵向验证。
- 最终优化：根据观测和系统测试证据，改善 Tutor、普通/科学/编程练习及课节交互。
- 三部分分别拆成小 Slice；一个 Slice 默认只承担一个主要风险轴。
- 成本展示统一使用人民币，不建设多币种、实时汇率、折扣、套餐或账单系统。

### 明确暂缓

- Postgres backup/restore、Qdrant rebuild runbook 和 storage reconciliation。
- Redis/Qdrant auth、容器非 root、端口、反向代理和 HTTPS hardening。
- 上述事项顺延至后续部署加固阶段，不视为取消或已经解决。

### 完成 Gate

- 质量与成本指标来自真实 trace/eval，并具有脱敏、归因和失败分类合同。
- 至少一条代表性学习主路径可跨 Web、API、worker、数据库和 adapter 重复运行。
- Tutor、普通练习和编程练习具有固定小样本质量基线，不以单次成功代替稳定证据。
- 优化项关联可复现问题、前后基线和回归结果；自动化、环境、真实 provider 和浏览器 Gate 分层报告。
- 备份恢复与部署安全暂缓风险在阶段总结和后续路线中保持可追踪。

## 9. Agent 基础能力演进大纲

本节是跨阶段导航，不是已接受的实现合同。各项能力的具体切片、数据模型、框架复用方式和验收线，在进入对应 Stage 时重新分析并通过 Spec/ADR 确认。

| 能力 | 已有基础 | 候选演进方向 | 必须后续分析 |
|---|---|---|---|
| RAG/citation | Stage 2 的资料、检索、权威回读和拒答 | 为课程生成和 Tutor 提供受控证据工具 | eval corpus、召回/拒答率、reranker 与上下文预算 |
| Agent runtime/tool | `hello_agents` Agent/Tool 资产与 Stage 2 单轮回答 | 从受控 Tutor 开始，定义停止、权限、预算、取消和最小 trace | 直接复用、产品 adapter 或新 runtime 的取舍 |
| Skill | framework/`academic_companion` 中的方法论资产 | 选择一个真实学习方法作为有版本的受控 Skill 样例 | 选择/组合规则、版本、输入输出、eval 和用户可见性 |
| MCP | 现有 MCP client/server 和 research 外部资料经验 | 只在明确需要外部资料/工具时引入一个有界的场景 | 白名单、授权、来源、隐私、超时、成本和失败退路 |
| 多 Agent | Course Architect、Lesson Writer、Tutor 的角色候选 | 只在职责和 artifact 真正可分时建立结构化交接 | 编排所有权、独立重试/取消、部分成功、人工 Gate 与成本放大 |
| Memory | 现有本地 memory 原型，但无产品事实合同 | 先区分当前 session/context，再基于学习事件、掌握度和复习形成长期 memory | 写入/提升规则、来源、纠正、删除、过期、冲突和效果 eval |

候选的整体节奏是：Stage 3 首次落地受控 Agent、RAG tool 和最小追踪；
Stage 4 将学习事件、掌握度、练习/复习和可管理 memory 形成闭环；Stage 5
统一 eval、运行轨迹和成本，并用系统测试驱动质量优化。备份恢复与部署安全
治理顺延到后续部署加固阶段。Skill、MCP 和多 Agent 的确切引入时点不在本
大纲中提前锁定。

## 10. 阶段依赖

```text
Stage 0R 基线
  -> Stage 1 产品壳
  -> Stage 2 资料生命周期
  -> Stage 3 章节与 Tutor
  -> Stage 4 练习与记忆
  -> Stage 5 可观测、系统验证与质量优化
```

后续 Stage 可以做设计预研，但不能绕过前一阶段的数据合同和验证 Gate 开始大规模实现。

## 11. 文档交付标准

每个 Stage 至少包含：

- `README.md`：目标、当前状态、文档入口。
- `specs/`：用户故事、范围、接口、失败模式和验收。
- `adr/`：不可逆或跨模块决策。
- `reviews/`：较大代码或阶段末审查记录。
- 阶段总结：实际完成、验证结果、暂缓风险和下一阶段输入。

实现细节过期后收敛进阶段总结，不在 `docs/` 根目录长期堆放多份当前计划。
