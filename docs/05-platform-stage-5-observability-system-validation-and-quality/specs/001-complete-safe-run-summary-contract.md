# Spec 001：完整且安全的运行摘要合同

状态：已于 2026-07-27 通过人工 Gate；可生成 GLM 实现任务包

日期：2026-07-27

适用范围：Platform Stage 5 第一部分 Slice 1A

## 1. 评审结论摘要

Slice 1A 建议只修复现有 Run Trace 的公开投影漂移：数据库已经记录课程、
Tutor、练习、评分、科学验证和代码执行 Run，但 API/Web 仍主要认识 Stage 3
的三个角色。

本 Slice 不新增数据库表或 migration，不引入 provider call、价格、人民币金额
或聚合 dashboard，也不修改任何生成、评分、Tutor、MCP 或执行行为。它只让
现有权威 `AgentRun/AgentToolCall` 能以一致、脱敏、可筛选的方式覆盖当前七种
角色和四类 owner，并为未知历史角色提供不会误导用户的降级显示。

### 1.1 待评审决策

1. 接受七种现有角色成为公开筛选值。
2. 接受四种明确 identity kind，并保留 `unknown` 安全降级。
3. 保持现有 Run/Tool 白名单字段，不在 Slice 1A 公开 provider/model 或金额。
4. 不修改历史 AgentRun；读取时从现有 owner 关系派生安全 identity。
5. Slice 1A 完成后再进入 provider call 与人民币成本事实的独立 ADR。

## 2. 已验证事实、本次建议与未决项

| 类型 | 内容 |
|---|---|
| 已验证事实 | `agent_runs` owner 约束已经支持 Course Job、Tutor Turn、Practice Job 和 Code Lab Job |
| 已验证事实 | 代码实际创建七种 role；API 默认列表能返回它们，但 role filter 只接受 Stage 3 三角色 |
| 已验证事实 | 后端已部分派生 Practice identity，尚未派生 Code Lab identity |
| 已验证事实 | Web role、identity 类型、标签和筛选只覆盖 Course Architect、Lesson Writer 与 Tutor |
| 已验证事实 | 现有 API 负面测试禁止公开 prompt、正文、evidence、input hash、provider/model、配置和日志 |
| 本次建议 | 补全七角色、四类 owner 和未知历史值的 API/Web 合同 |
| 本次建议 | 沿用原接口和数据表，不新增 migration、金额或新页面 |
| 待人工选择 | 是否接受第 7 节的 role/kind/identity 白名单和第 14 节 Gate |

## 3. Goal / Context / Constraints / Done when

| 项目 | 内容 |
|---|---|
| Goal | 维护者能够在 Workspace 的运行记录中正确识别、筛选和查看当前全部 Course、Tutor、Practice 与 Code Lab Run |
| Context | Stage 3 已建立安全 Run Trace；Stage 4 扩展了 owner/role，但公开 API/Web 合同未完整同步 |
| Constraints | 不改 schema；不公开敏感内容；不新增 provider/cost 事实；不改变业务状态、重试、删除或执行路径 |
| Done when | 七角色与四类 owner 的列表、筛选、详情、工具阶段、删除降级和 Web 状态均可验证，未知角色不崩溃、不空白、不误标 Tutor |

## 4. 术语

| 术语 | 含义 |
|---|---|
| Run | 一个业务 attempt 的 `AgentRun` 审计摘要 |
| Tool Call | Run 中一个确定性或外部工具阶段的 `AgentToolCall` 摘要；不是 provider call |
| Owner | Run 唯一关联的 Course Job、Tutor Turn、Practice Job 或 Code Lab Job |
| Role | 执行职责，例如 `tutor`、`exercise_author` 或 `code_execution` |
| Identity | 从 owner 关系派生的安全业务身份，用于显示课程、课节、任务类型或代码语言 |
| Unknown fallback | 历史或未来未知 role/kind 的安全显示，不猜测业务含义 |

## 5. 用户路径

### 5.1 查看 Workspace 运行记录

1. 用户进入现有 Workspace“运行记录”入口。
2. 页面列出最近 Run，显示安全业务身份、角色、attempt、状态、token、时间和
   duration。
3. 用户可以按课程、角色和状态筛选。
4. 展开一条 Run 后，按 ordinal 查看脱敏 Tool Call 阶段、结果数量、latency 和
   稳定错误。
5. 运行中记录继续轮询；终态记录不进行无意义轮询。

### 5.2 识别不同业务

- Course Architect/Lesson Writer：显示课程生成类型、课程和可用课节。
- Tutor：显示本课或本课程辅导、课程和可用课节。
- Exercise Author：显示练习生成、课程和课节。
- Answer Grader：显示练习评分、课程和课节，不显示题目或用户答案。
- Scientific Solution Grader：显示科学题验证/评分、课程和课节，不显示公式
  输入或 Wolfram 原始 observation。
- Code Execution：显示代码执行、语言和可用课程/课节，不显示 source、stdin、
  stdout、stderr 或编译输出。

### 5.3 未知与已删除

- 未知 role 显示“其他运行”，并保留原始稳定 role 值作为非敏感辅助标识；不能
  显示空白、抛出渲染错误或按 Tutor 解释。
- owner 存在但 Course/Lesson 已删除或不可回读时，显示“已删除对象”和安全
  kind/role，不复活标题或内容。
- owner 本身不可回读时，identity kind 为 `unknown`，不猜测关联关系。

## 6. 范围

### 包含

- 现有两个 Agent Run GET 接口的 role filter 和安全 identity 投影；
- API schema、service 和 focused tests；
- Web API 类型、标签、筛选、identity 文案、错误文案和响应式状态；
- 七角色、四 owner、未知 role、已删除 owner 和 Workspace 隔离矩阵；
- 现有 ToolCall 安全详情与轮询行为回归。

### 明确不做

- 新表、migration、provider call、provider/model/rate snapshot；
- 人民币金额、成本聚合、预算预测或账单；
- eval 趋势、CI 系统测试平台或完整 Quality & Cost 页面；
- 日志下载、prompt/evidence/response 查看器；
- 修改 Course、Tutor、Practice、Science、MCP 或 Code Lab 业务逻辑；
- 新的 Agent role、MCP capability、自主多 Agent、认证或多租户；
- 为未知 role 增加猜测式自动分类。

## 7. 公开合同

### 7.1 已知 Role

公开筛选接受：

```text
course_architect
lesson_writer
tutor
exercise_author
answer_grader
scientific_solution_grader
code_execution
```

response 中 `role` 继续使用字符串，而不是数据库 enum。原因是历史数据和未来
版本可能包含未知值；读取路径必须安全降级，不能因为 Web/客户端版本较旧而使
整个列表失败。

### 7.2 Identity Kind

建议公开：

```text
course_generation
tutor
practice
code_execution
unknown
```

### 7.3 Identity 白名单

`identity` 允许：

| 字段 | 含义 |
|---|---|
| `kind` | 第 7.2 节安全类型 |
| `job_type` | Course/Practice Job 的稳定类型；其他类型为 `null` |
| `course_id` | 可回读 Course ID |
| `course_title` | 活跃 Course 的显示标题 |
| `course_deleted` | Course/owner 不可安全回读 |
| `lesson_id` | 可回读 Lesson ID |
| `lesson_title` | 同 Workspace Lesson 标题 |
| `tutor_scope` | `lesson|course|null` |
| `code_language` | `python|java|cpp|null`，仅 Code Lab |

不新增 Practice Item、Attempt、Set、Code Run 或 Job 的内部 ID。用户通过业务页
执行重试、取消和删除；运行记录仍是只读诊断入口。

### 7.4 Run 与 Tool 白名单

Run 继续只返回：

- ID、role、status、attempt、step；
- 已记录 input/output token；
- created/completed time 和派生 duration；
- 稳定 error code；
- 第 7.3 节 identity。

Tool 继续只返回：

- tool name、ordinal、status、result count、latency、error code、created time。

Slice 1A 不新增 provider/model、金额、input hash 或原始 payload。

## 8. API

沿用：

```text
GET /api/v1/workspaces/{workspace_id}/agent-runs
GET /api/v1/workspaces/{workspace_id}/agent-runs/{run_id}
```

列表参数：

| 参数 | 合同 |
|---|---|
| `course_id` | 可选；保持 Workspace 边界，覆盖 Course/Tutor/Practice；Code Lab 只在有关联 Course 时命中 |
| `role` | 可选；接受第 7.1 节七种值 |
| `status` | 可选；`running|succeeded|failed|canceled` |
| `limit` | 1-50，默认 20 |

未知 filter 仍返回 422。未知历史 response role 不导致 500。不存在或跨 Workspace
的 Run 仍返回 404。

本 Slice 不增加分页 cursor、时间范围、批量导出或聚合接口；这些留给 Slice 1C
评审。

## 9. Identity 派生规则

### Course Generation

- owner 为 CourseGenerationJob；
- `kind=course_generation`；
- `job_type` 来自稳定 Job 类型；
- 只读取同 Workspace、active Course 和同 Workspace Lesson 标题。

### Tutor

- owner 为 TutorTurn；
- `kind=tutor`；
- scope 来自 Turn；
- Course 从同 Workspace、active、未删除 Tutor Session 回读。

### Practice

- owner 为 PracticeJob；
- `kind=practice`；
- generation job 直接读取 Course/Lesson；
- grading job 经 Attempt -> Item -> Set 回读 Course/Lesson；
- 任一跨 Workspace 或断链都降级为已删除/unknown，不继续猜测。

### Code Execution

- owner 为 CodeLabJob，再读取同 Workspace CodeLabRun；
- `kind=code_execution`；
- `code_language` 只允许 `python|java|cpp`，异常历史值不原样公开，返回 `null`；
- 可读取关联 Course/Lesson 标题；
- 不读取 source、stdin、compile output、stdout、stderr、runtime URL 或 MCP 配置。

## 10. 状态与失败行为

| 场景 | 行为 |
|---|---|
| Run 进行中 | duration 为 `null`，token 只显示已提交事实，不推断最终值 |
| usage 全缺 | 显示“token 未报告” |
| 单一 token 维度缺失 | 已知维度正常显示，未知维度显示 `?` |
| 已知 role + owner 完整 | 显示对应业务身份 |
| 未知 role | 显示“其他运行”，不按 Tutor 或其他已知角色解释 |
| owner/Course/Lesson 删除 | 显示安全删除状态，不回读正文 |
| Code Lab 私有输出存在 | 运行摘要仍不返回任何代码和输出正文 |
| tool name 未知 | 显示稳定 tool name 的安全文本，不阻塞详情 |
| API 列表读取失败 | 页面显示可重试错误，不影响 Workspace 其他功能 |
| 单条详情读取失败 | 只在展开区域显示错误，列表保持可用 |

## 11. 安全与删除

Stage 3 ADR 007 的禁止字段继续完整生效。尤其禁止：

- prompt、问题、回答、题干、选项、用户答案、rubric、feedback；
- evidence、chunk、课程正文、代码、stdin/stdout/stderr、编译输出；
- Tool input/input hash、Wolfram observation、provider raw response；
- provider key/Base URL、连接串、内部 URL、绝对路径、环境变量和日志。

Slice 1A 不改变删除权威：

- Workspace 删除继续清理所属 Run/Tool；
- Tutor Turn 删除继续级联其 Run/Tool；
- Practice/Code Lab 删除继续遵守已有 Stage 4 合同；
- identity 读取不能复活已删对象。

## 12. 文件边界

候选修改仅限：

- `apps/api/learn_platform_api/routers/agent_runs.py`
- `apps/api/learn_platform_api/schemas/agent_runs.py`
- `apps/api/learn_platform_api/services/agent_runs.py`
- `apps/api/tests/test_agent_run_api.py`
- 必要的窄小 Stage 5 focused test
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/AgentRunsPanel.tsx`
- 现有相关样式和必要的前端测试

不修改 ORM、migration、worker、provider adapter、Practice artifact、Tutor prompt
或 MCP server。

## 13. 验证与完成 Gate

### API focused

- 七种已知 role 的列表、详情和 filter；
- Course/Tutor/Practice/Code Lab 四种 identity；
- Practice grading 断链、Code Lab 无课程、owner 删除和未知 role；
- Workspace/course filter 隔离；
- tool ordinal、unknown tool 和详情 404；
- 原有 forbidden-key 递归负面测试；
- response 不出现 provider/model/cost/code/answer 等禁止字段。

### Web

- 七角色中文标签和筛选；
- 四 identity 文案；
- 未知 role、unknown kind、已删除对象和缺失 token；
- running 轮询、列表错误、详情错误和空状态；
- 长课程/课节/role 文案在桌面和窄视口不重叠；
- 未知 role/tool 不引发运行时异常。

### 回归

- 现有 `test_agent_run_api.py`；
- 相关 Stage 3/4 safe trace tests；
- Web lint/build；
- `git diff --check`；
- Chrome 桌面与移动视口人工 smoke。

本 Slice 是公开 API/Web 行为修复。只有自动化、网络响应安全检查和真实浏览器
smoke 均通过，才可标记完成。

## 14. 人工 Gate（已接受）

1. 是否接受 Slice 1A 只补全现有运行摘要，不做 provider/cost schema？
2. 是否接受第 7.1 节七种公开筛选 role？
3. 是否接受 `course_generation|tutor|practice|code_execution|unknown` 五种 identity kind？
4. 是否接受 Code Lab 只公开语言和课程/课节身份，不公开代码或执行输出？
5. 是否接受 response role 保持字符串，并为未知值显示“其他运行”？
6. 是否接受不修改历史 Run，只在读取时派生安全 identity？
7. 是否接受沿用现有两个 GET 接口，不在 Slice 1A 增加聚合或分页？
8. 是否接受第 11 节敏感字段和删除边界？
9. 是否接受第 12 节文件边界与第 13 节验证范围？
10. 是否确认通过 Slice 1A 后，再单独评审 Provider Call 与人民币成本 ADR？

以上 Gate 已于 2026-07-27 获人工整体接受。实现不得扩大到 Provider Call、
人民币成本、聚合 dashboard、migration 或新的业务角色；任何合同冲突必须停止
并重新进入人工 Gate。
