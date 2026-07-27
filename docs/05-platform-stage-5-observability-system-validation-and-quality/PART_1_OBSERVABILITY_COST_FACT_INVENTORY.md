# Stage 5 第一部分事实盘点：可观测与成本

状态：事实盘点完成；候选边界不构成 Spec/ADR 或实现批准

日期：2026-07-27

## 1. 结论摘要

当前仓库不是“没有可观测数据”，而是已经形成多套局部事实，尚未统一：

- `AgentRun/AgentToolCall` 已覆盖课程、Tutor、练习、评分、科学验证和代码执行，
  是最接近统一运行事实的主干。
- RAG query/answer、Tutor Turn、Practice Job、Code Lab Run 和离线 eval 又分别
  保存模型、token、延迟或结果指标。
- Stage 3 的运行记录 API/Web 仍主要认识课程与 Tutor，已经落后于 Stage 4
  新增的练习、评分、科学验证和代码执行角色。
- 当前没有 provider call 级事实、统一 provider/model 快照、人民币价格快照、
  成本事件或质量/成本聚合视图。
- token 缺失语义在不同链路不完全一致，现有总量不能直接无条件换算金额。

因此，第一部分不适合直接建设 dashboard。应先修复现有运行摘要的投影漂移，
再建立 provider call/usage 权威事实，最后做人民币成本聚合和用户界面。

## 2. 核对范围

本次读取并交叉核对：

- Stage 3 Spec 005、ADR 007、Tutor 成本解释材料和阶段总结；
- Stage 4 Practice/MCP/稳定化的模型、worker、eval 与总结；
- SQLAlchemy 模型和 Alembic migration 现状；
- Course、Tutor、Practice、RAG、Code Lab 和 Science 服务；
- 运行记录 API/schema/Web；
- Stage 3/4 离线 eval manifest、runner、report 和 focused tests。

没有读取或输出 `.env`、provider key、上传原文、真实 prompt、用户答案或运行
日志正文。

## 3. 当前权威事实矩阵

| 事实 | 当前来源 | 已有字段 | 当前限制 |
|---|---|---|---|
| 通用 Agent 运行 | `agent_runs` | owner、workspace、role、attempt、status、step、input/output token、error、开始/完成时间 | 无 provider/model、provider call 数、调用阶段、价格或金额 |
| 通用工具阶段 | `agent_tool_calls` | tool、ordinal、status、result count、latency、error；内部还保存 input hash | Tool 与 provider call 不是同一概念；公开投影不返回 input hash |
| 课程生成 | `course_generation_jobs` + AgentRun | job 类型、attempt、队列/lease/error；token 在 AgentRun | Job 无不可变 provider/model 快照 |
| Tutor | `tutor_sessions`、`tutor_turns` + AgentRun | Session 有 provider/model；Turn/Run 有 token、状态和时间 | 执行调用仍读取 worker 当前 settings，Session 字段不是每次 provider call 或 Run 的已验证快照 |
| Practice | `practice_jobs` + AgentRun | generation/grading job、attempt、token、artifact version、错误 | 生成和评分使用不同 model，但 Job/Run 不记录实际 provider/model |
| RAG query | `rag_query_traces` | embedding model、candidate/result count、latency | 无 embedding provider usage/token，不能可靠换算金额 |
| RAG answer | `rag_answer_traces` | provider/model、input/output token、retrieval/generation latency、status/error | 与 AgentRun 分离，无统一运行归因和公开趋势 |
| Code Lab | `code_lab_runs/jobs` + AgentRun/ToolCall | language、runtime、duration、状态、稳定错误、MCP snapshot | 无货币 usage；self-host 执行不等于零资源成本 |
| Wolfram/science | ToolCall、authorization、capability status | 调用状态、次数、latency、schema/capability snapshot | 无供应方 usage 或人民币成本事实 |
| API 请求 | JSON request log | request ID、method、path、status、duration | 没有统一关联业务 Run；部分 worker 日志仍是自由文本 |
| 离线 eval | `stage3_eval`、`stage4_eval` 本地 artifact | case/version、status、error category、duration、部分 usage/quality 指标 | 不进 Postgres，无历史趋势；Stage 4 manifest 没有显式编程/科学 case |

## 4. `AgentRun` 实际覆盖

当前 `AgentRun` owner 约束支持：

- Course Generation Job；
- Tutor Turn；
- Practice Job；
- Code Lab Job。

代码中实际创建的角色至少有七种：

```text
course_architect
lesson_writer
tutor
exercise_author
answer_grader
scientific_solution_grader
code_execution
```

这说明 `AgentRun` 已经是跨 Stage 3/4 的运行主干，不宜再建立第二套通用 Run
事实。但它目前只适合描述整个 attempt，不能解释一次 attempt 内具体发生了几次
provider 调用、哪次是计划/生成/repair、每次使用哪个模型或花费多少。

## 5. 已确认的投影漂移

### 5.1 API 过滤合同停留在 Stage 3

运行列表默认会返回 Workspace 下全部 AgentRun，后端 response schema 的 `role`
也是普通字符串；但 API 的 `role` 过滤只接受：

```text
course_architect | lesson_writer | tutor
```

因此练习、评分、科学验证和代码执行 Run 可以出现在列表中，却不能通过公开 API
按这些角色筛选。

### 5.2 Web 类型和标签停留在 Stage 3

Web 的 `AgentRunRole`、角色标签和筛选项同样只有三个 Stage 3 角色。Practice
identity 已由后端部分支持，但 Web 的 identity 类型只声明 course/tutor，并会把
非 course identity 落入 Tutor 展示逻辑。Code Lab owner 在后端 identity 中也
没有独立分支。

结果是 Stage 4 Run 可能出现空角色标签、错误业务身份或无法筛选。当前 focused
测试覆盖 Stage 3 三角色和一个 Practice identity API 案例，但没有覆盖完整七
角色 API/Web 矩阵。

## 6. usage 与成本事实

### 6.1 已有可靠部分

- Tutor 和新版 Practice 链路按 input/output 维度聚合；任一 provider call 未
  报告某维度时，该维度保持 `null`，不会用文本估算冒充 usage。
- AgentRun 的开始/完成时间可以派生 attempt duration。
- ToolCall 可提供部分检索、Skill、MCP 和提交阶段的 latency。
- RAG Answer Trace 已保存 provider/model 与生成 token。
- Practice generation 使用独立 `practice_generation_model`；Tutor、Course、
  RAG answer 和 Practice grading 使用产品生成模型。

### 6.2 不可直接计费的部分

- AgentRun 不保存 provider/model，无法证明历史 Run 实际用了当前配置中的哪个
  模型。
- provider call 没有独立 ordinal、phase、status、latency 和 usage 事实；
  `step_count` 是业务逻辑步数，`AgentToolCall` 又只表示 Tool，二者都不能当作
  provider call 数。
- Course/RAG Answer 的部分聚合使用 `or 0`，当单次调用未报告 token 时可能把
  “未知”折叠进总数；Lesson Writer 还会在 output usage 缺失时用生成 JSON
  长度估算并写入 Run token。这一语义与 Tutor/Practice 不一致，不能直接用于
  金额计算。
- 当前 provider response 只保留 prompt/completion token，未建立缓存命中 token、
  供应方账单金额或折扣事实。
- embedding 调用没有 provider usage token；Wolfram 也没有可计费 usage。
- 代码执行保存时间和运行环境，不产生可直接换算的 provider token 成本。
- 仓库没有人民币价格配置、价格版本、成本事件或历史金额字段。

结论：现有 token 可以展示，但不能把所有历史 Run 按当前配置直接换算成“真实
人民币成本”。

## 7. 人民币成本的最小候选口径

顶层 Gate 已确认只使用人民币，不建设多币种、实时汇率、折扣、套餐或账单
系统。后续 Spec/ADR 可基于以下最小边界评审：

- 金额名称使用“计算成本”，不宣称等于 provider 最终账单。
- 只对同时具有完整 provider/model、完整 usage 和人民币单价版本的调用计算。
- 单价使用人工维护的人民币 input/output 单价快照；不在线抓取汇率或价格。
- 缺 provider/model、缺任一 token 维度或缺单价时，金额为 `unknown`，继续展示
  usage 和缺失原因。
- 暂不计算 embedding、Wolfram 和 self-host Code Lab 金额，除非后续获得可靠
  usage/单价事实。
- 历史价格不能读取“当前设置”反推；价格版本必须与调用事实绑定，或明确标记
  历史金额不可计算。

这是一项候选建议，不批准具体字段、精度、四舍五入或 migration。

## 8. Eval 与质量关联现状

- Stage 3 eval 有 22 个 case，覆盖 Course Architect、Lesson Writer、Tutor 和
  cross；包含 3 个观察 case 与 Tutor 配对 usage。
- Stage 4 eval 有 38 个 case，覆盖 Exercise Author、Answer Grader、Practice
  和 cross；包含 3 个观察 case。
- 两套报告都只支持 `offline` mode，写入 Git 忽略的本地 artifact。
- 报告保留 case/version、duration、稳定错误分类和有限 usage，不保存敏感正文。
- 当前没有 eval run/result 产品表，也没有把一次 eval 与 AgentRun/代码版本形成
  可查询历史趋势。
- Stage 4 固定 manifest 没有显式 coding/scientific case；这些能力主要由其他
  focused tests、环境 Gate 和人工 smoke 证明。

第一部分可定义安全关联键和读取边界，但不应提前把第二部分的系统测试建设全部
吸收进来。

## 9. 日志与保留

- HTTP middleware 使用 JSON 日志并生成 request ID，但 request ID 没有统一写入
  AgentRun/Job，因此不能稳定跨 API 和 worker 串联。
- JsonFormatter 有字段白名单，部分 worker/service 仍使用自由文本插值和
  exception logging；日志不是稳定的产品观测事实。
- Workspace 删除会清理关联 Run/Tool/RAG trace；当前没有独立的 trace 保留期、
  聚合降采样或全局清理策略。
- 第一部分不得通过保存 prompt、回答、用户答案、evidence、源文件、Tool 原始
  输入输出或 provider 原始错误来弥补诊断不足。

## 10. 已验证基线

执行：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_agent_run_api.py `
  apps/api/tests/test_stage3_eval.py `
  apps/api/tests/test_stage4_eval.py
```

结果：`24 passed in 36.74s`。

首次使用系统 `python` 失败，因为该解释器未安装 pytest；随后使用仓库现有
Python 3.12 环境复跑通过。该结果只证明现有安全投影和 eval report 合同基线，
不证明七角色 Web 展示、provider call 事实或人民币成本已经实现。

## 11. 需要 Spec/ADR 决定的问题

1. provider call 是建立独立权威表，还是只扩展 AgentRun；不能把 ToolCall 改名
   后混用。
2. provider/model、usage、phase、latency、finish reason、错误码和人民币单价
   快照分别落在哪一层。
3. 发送成功但本地超时/取消、usage 未返回时如何记录“可能计费但金额未知”。
4. 是否以及如何修复历史 Run；默认不应读取当前配置反填历史 provider/model。
5. Run/Tool/provider call/cost 记录的 Workspace 删除、单条 Tutor 删除和保留期。
6. eval 是否继续只保留本地 artifact，还是保存最小 run summary 以支持趋势。
7. Quality & Cost 页面是 Workspace 级还是全实例级；当前单用户产品也必须保持
   Workspace 查询边界。

## 12. 事实盘点结论

第一部分的首要工作不是金额换算，而是建立完整、诚实、可删除的运行与 provider
调用事实。现有 `AgentRun` 应继续作为 attempt 主干；Stage 3 的安全白名单原则
继续有效。任何 schema、价格快照、成本事件或保留策略都属于 L3 决策，必须先有
Spec/ADR 和人工 Gate。
