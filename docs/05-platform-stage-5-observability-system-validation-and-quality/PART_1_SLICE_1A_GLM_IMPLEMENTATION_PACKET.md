# Stage 5 第一部分 Slice 1A：GLM 实现任务包

状态：正式实现任务包；Spec/前端 Gate 已于 2026-07-27 通过

## 1. 任务身份

仓库：

```text
C:\Users\Admin\Desktop\HelloAgents-LearnPlatform
```

当前分支：`main`

目标：补全现有 Workspace“运行记录”的安全 API/Web 投影，使当前七种 Agent
role 和四类 owner 都能正确列出、筛选和展示；不修改数据库或任何业务执行路径。

这是单一风险轴的公开投影修复，不是可观测与成本的完整实现。

### 1.1 运行环境

- 操作系统与终端：Windows PowerShell。
- 工作目录：`C:\Users\Admin\Desktop\HelloAgents-LearnPlatform`。
- Python：只使用仓库现有 `.\.venv\Scripts\python.exe`，运行测试前设置
  `$env:PYTHONPATH='apps/api'`。
- Web：在 `apps/web` 使用现有 Node/npm 环境和 `npm.cmd`；不得安装或升级依赖，
  不得重建 lockfile。
- 本 Slice 的自动化验证不得调用真实 provider、外部付费服务或真实 OCR。
- 不要求为本 Slice启动 Docker Compose 或修改本地服务配置。若既有测试明确依赖
  当前不可用的 Postgres、Redis、Qdrant 或浏览器环境，应记录原始阻塞并停止对应
  验证，不得擅自改成 SQLite、mock 或跳过测试。
- Chrome 人工 smoke 由 Codex 接回实现后执行，GLM 不以截图或源码检查替代它。

## 2. 开始前必须完整读取

按顺序读取：

1. 根 `AGENTS.md`
2. `docs/README.md`
3. `docs/LEARNING_AGENT_BLUEPRINT.md`
4. `docs/SELF_HOST_DEVELOPMENT_ROADMAP.md`
5. `docs/DATABASE_AND_DEPLOYMENT_PLAN.md`
6. `docs/AGENT_COLLABORATION_PLAYBOOK.md`
7. `docs/GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md`
8. `docs/05-platform-stage-5-observability-system-validation-and-quality/README.md`
9. `docs/05-platform-stage-5-observability-system-validation-and-quality/STAGE_5_INPUTS.md`
10. `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_OBSERVABILITY_COST_FACT_INVENTORY.md`
11. `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_CANDIDATE_SLICE_PLAN.md`
12. `docs/05-platform-stage-5-observability-system-validation-and-quality/specs/001-complete-safe-run-summary-contract.md`
13. `docs/05-platform-stage-5-observability-system-validation-and-quality/PART_1_SLICE_1A_FRONTEND_CONCEPT.md`
14. `docs/03-platform-stage-3-chapter-learning-and-tutor/specs/005-repeatable-quality-gates-and-safe-run-summaries.md`
15. `docs/03-platform-stage-3-chapter-learning-and-tutor/adr/007-eval-artifacts-and-safe-trace-projection.md`

再读取相邻代码和测试：

- `apps/api/learn_platform_api/db/models.py` 中 AgentRun、AgentToolCall、
  CourseGenerationJob、TutorSession/Turn、PracticeJob/Attempt/Item/Set 和
  CodeLabJob/Run；
- `apps/api/learn_platform_api/routers/agent_runs.py`
- `apps/api/learn_platform_api/schemas/agent_runs.py`
- `apps/api/learn_platform_api/services/agent_runs.py`
- `apps/api/tests/test_agent_run_api.py`
- `apps/api/tests/test_practice_api.py` 中运行 identity 案例；
- `apps/web/src/lib/api.ts` 的 AgentRun 类型和请求；
- `apps/web/src/app/AgentRunsPanel.tsx`
- `apps/web/src/styles.css` 的运行记录样式。

不要只依赖本任务包摘要。

## 3. Dirty Worktree 与所有权

开始时运行：

```powershell
git status --short --branch
git diff --stat
```

当前已知：

- Stage 5 规划、事实盘点、已接受 Spec/前端概念和本任务包是 Codex/用户的预期
  文档改动，不得回滚、覆盖或改成未接受状态。
- `.tmp/` 与 `artifacts/` 是已存在的未跟踪目录，所有权未知；不要读取、移动、
  删除、提交或用于测试输出。
- 发现其他未知改动时保留并绕开；若直接阻塞本任务，停止并报告。

禁止使用 `git reset --hard`、`git checkout --`、stash、clean 或任何破坏性
命令。不得 commit 或 push。

## 4. 已接受合同

### 4.1 已知 Role

公开 filter 接受：

```text
course_architect
lesson_writer
tutor
exercise_author
answer_grader
scientific_solution_grader
code_execution
```

response `role` 保持字符串，以安全读取历史/未来未知值。未知 role 在 Web 显示
“其他运行”，不得空白、崩溃或落入 Tutor 分支。

### 4.2 Identity Kind

```text
course_generation
tutor
practice
code_execution
unknown
```

允许字段只有：

```text
kind
job_type
course_id
course_title
course_deleted
lesson_id
lesson_title
tutor_scope
code_language
```

Code Lab 只允许公开 `python|java|cpp` 语言和可用 Course/Lesson 身份。异常历史
language 返回 `null`，不原样公开。

### 4.3 安全字段

Run/Tool 现有白名单保持不变，只增加安全 identity 字段。严禁新增：

- provider、model、价格、人民币金额；
- prompt、问题、回答、题干、选项、用户答案、rubric、feedback；
- evidence、chunk、课程正文、source code、stdin/stdout/stderr、compile output；
- Tool input/input hash、Wolfram observation、raw provider response；
- key、Base URL、内部 URL、连接串、绝对路径、环境变量或日志。

### 4.4 API

沿用且只沿用：

```text
GET /api/v1/workspaces/{workspace_id}/agent-runs
GET /api/v1/workspaces/{workspace_id}/agent-runs/{run_id}
```

不新增分页、聚合、时间范围、导出或写操作。role filter 扩展到七种已知值；
未知 filter 仍为 422。列表中的未知历史 role 仍能安全读取。

## 5. 明确禁止

- 不改 ORM、Alembic migration 或数据库约束。
- 不新增 provider call、cost event、价格配置或金额字段。
- 不修改 Course、Tutor、Practice、Science、MCP、Code Lab worker/runtime。
- 不修改 Practice artifact/schema、评分、预算、重试或队列状态。
- 不新增 Agent role、identity 猜测、MCP capability 或新导航。
- 不把 ToolCall 改造成 provider call。
- 不引入新的前端测试框架、状态管理库、图表库或设计系统。
- 不写源码字符串检查、复制生产 `if/raise` 的假测试或只测 helper 的捷径。
- 不运行真实 provider、Judge0、Wolfram、OCR 或付费操作。
- 不为固定 fixture、课程名、题干、关键词或截图硬编码结果。

## 6. 建议实现顺序

### Phase A：先补行为测试

扩展 `test_agent_run_api.py`，使用真实 ORM 关系和公开 HTTP endpoint，不直接调用
内部 helper 代替 API 行为。

至少覆盖：

1. 七种 role 都能在默认列表中返回。
2. 七种已知 role filter 都返回正确 Run。
3. Course Architect/Lesson Writer identity。
4. Tutor lesson/course identity。
5. Practice generate identity。
6. Practice grade 经 Attempt -> Item -> Set 回读 identity。
7. Code Lab 有 Course/Lesson 和无 Course/Lesson 两种 identity。
8. Code Lab `python|java|cpp` 与异常历史 language 的安全投影。
9. 未知历史 role 能读取且不改变为已知 role。
10. `course_id` filter 覆盖 Course、Tutor、Practice 和有关联 Course 的 Code Lab。
11. owner/Course/Lesson 缺失或已删除时的降级。
12. Workspace 隔离、详情 404、limit/status filter 和 Tool ordinal。
13. 递归 forbidden-key 测试加入代码、执行输出、Practice/Science 私有字段。

反事实要求：移除对应 identity 分支、role filter 或安全 language 校验时，相关
测试必须失败。

不要为了测试方便取消 `AgentRun` one-owner 约束或绕过真实模型关系。

### Phase B：后端安全投影

修改 router/schema/service：

- 建立单一已知 role 常量或类型来源，避免 router/test 多处漂移，但不要引入大型
  registry 抽象。
- role query filter 接受七种已知值。
- response role 仍为字符串。
- `AgentRunIdentity` 增加 `code_language`，kind 支持五种安全值。
- `_identity` 使用显式 owner 分支：
  - Course Generation；
  - Tutor；
  - Practice generation/grading；
  - Code Lab Job -> Code Lab Run；
  - defensive `unknown`。
- 每次回读都验证 Workspace 和 active/deleted 边界。
- `course_id` filter 增加有关联 Course 的 Code Lab Run。
- 不读取或返回任何私有正文。

不要以异常吞噬所有错误；只对断链/删除做合同内降级，真实数据库编程错误仍应被
测试发现。

### Phase C：Web 类型与渲染

更新：

- 已知 filter role 类型包含七种值；
- response role 能容纳未知字符串，不能用不真实的窄 union 欺骗 TypeScript；
- identity kind/`code_language` 与 API 一致，同时保留未知值安全降级；
- 角色标签使用安全函数，未知 role 返回“其他运行”；
- identity 文案使用显式 switch，不允许“非 course 即 Tutor”的 fallthrough；
- 筛选项加入四种 Stage 4 role；
- Code Lab 显示语言和可用 Course/Lesson；
- 已知稳定错误可增加短中文映射，未知错误保持通用安全文案；
- unknown Tool 显示稳定 name，不读取参数；
- 展开按钮补齐 `aria-expanded` 和关联详情区域；
- 自动轮询不得重置筛选、焦点或展开状态。

样式沿用 `styles.css` 现有运行记录结构。按照已接受响应式矩阵处理长身份、角色、
状态和 Tool name；不把页面重做成卡片 dashboard。

### Phase D：验证与报告

全部验证通过后，写实现报告：

```text
docs/05-platform-stage-5-observability-system-validation-and-quality/
PART_1_SLICE_1A_GLM_HANDBACK.md
```

报告只写修改文件、行为、验证结果、未解决问题和供 Codex 复核的风险；不得包含
绝对路径、配置、日志、provider 信息或用户数据。

## 7. 验证命令

### API focused

使用仓库现有 Python 环境，不安装或升级依赖：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_agent_run_api.py `
  apps/api/tests/test_stage3_eval.py `
  apps/api/tests/test_stage4_eval.py
```

根据实际新增测试文件，将其显式加入命令。再运行相关 owner 回归：

```powershell
$env:PYTHONPATH='apps/api'
.\.venv\Scripts\python.exe -m pytest -q `
  apps/api/tests/test_practice_api.py `
  apps/api/tests/test_mcp_orm_and_schema.py
```

若整文件包含与本 Slice 无关的环境阻塞，先运行精确 `-k` 范围并如实报告；不得
删除测试或写成“视为通过”。

### Web

```powershell
Set-Location apps/web
npm.cmd run lint
npm.cmd run build
Set-Location ../..
```

### 文档与工作区

```powershell
git diff --check
git status --short --branch
git diff --stat
```

不得运行真实 OCR。人工 Chrome smoke 和更广独立回归由 Codex 接回后组织。

## 8. 完成标准

只有同时满足以下条件才可交回：

- 七角色/四 owner/unknown fallback 的 HTTP 行为测试通过；
- Code Lab 私有字段和 Stage 3 禁止字段负面测试通过；
- API 未新增 schema/migration/provider/cost 行为；
- Web 类型不再假设 response 永远只有三个 role；
- 未知 role/kind/tool 不崩溃且不误标 Tutor；
- 桌面/窄视口样式完成，lint/build 通过；
- `git diff --check` 通过；
- handback 明确所有未运行或环境阻塞的检查。

GLM 的“完成”只是实现候选交回，不代表 Slice 1A 通过。Codex 将独立检查 diff、
复跑测试、组织适用 OCR 预检和人工浏览器 Gate。

## 9. 停止并报告

出现以下任一情况，停止对应部分，不自行改变合同：

- 必须 migration 才能完成；
- 现有 ORM owner 关系与 Spec 冲突；
- 需要公开代码、答案、prompt、provider/model 或内部配置才能显示 identity；
- 必须修改业务 worker、重试、预算、删除或状态机；
- 现有未知 dirty change 与目标文件直接冲突；
- Web 无法在现有导航和行内展开结构中满足状态矩阵；
- 测试只能通过硬编码 fixture 或绕过公开 endpoint。

## 10. Handback 格式

```markdown
# Slice 1A GLM Handback

## 修改文件

## 合同实现
- 七角色与 filter
- 四 owner identity
- unknown/deleted fallback
- 安全字段
- Web 状态与响应式

## 验证
- 命令
- 结果
- 未运行及原因

## 未解决问题

## Codex 需要重点复核
```

停在这里。不要运行真实 provider、Judge0、Wolfram 或 OCR，不要 commit/push，
不要修改 Slice 1B/1C，不要宣布 Slice 1A 已完成。
