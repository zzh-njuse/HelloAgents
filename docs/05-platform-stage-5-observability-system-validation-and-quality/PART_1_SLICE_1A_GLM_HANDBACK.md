# Slice 1A GLM Handback

## 修改文件

- `apps/api/learn_platform_api/routers/agent_runs.py` — RunRole 扩展为七种已知值
- `apps/api/learn_platform_api/schemas/agent_runs.py` — AgentRunIdentity 增加 code_language 字段
- `apps/api/learn_platform_api/services/agent_runs.py` — _identity 增加 Code Lab owner 分支、code_language 安全投影、course_id filter 覆盖 Code Lab Run、unknown 默认 kind
- `apps/api/tests/test_agent_run_api.py` — 新增 13 个行为测试覆盖七角色/四 owner/unknown fallback/code_language 安全投影/forbidden-key 扩展
- `apps/web/src/lib/api.ts` — AgentRunRole 扩展为七种值；AgentRunIdentity 增加 kind 五种值和 code_language；AgentRunSummary.role 改为 string 容纳未知值
- `apps/web/src/app/AgentRunsPanel.tsx` — 角色标签/筛选项/identity 文案/错误码映射/Tool 标签/aria-expanded/安全角色标签函数

## 合同实现

- 七角色与 filter
  - router RunRole Literal 扩展为 course_architect/lesson_writer/tutor/exercise_author/answer_grader/scientific_solution_grader/code_execution
  - 未知 role filter 仍返回 422
  - 未知历史 role 在 response 中保持原始字符串，不改变为已知值
- 四 owner identity
  - CourseGenerationJob → kind=course_generation
  - TutorTurn → kind=tutor
  - PracticeJob → kind=practice（generation 直接读 Course/Lesson；grading 经 Attempt→Item→Set 回读）
  - CodeLabJob → kind=code_execution（经 CodeLabRun 读取 language 和可选 Course/Lesson）
- unknown/deleted fallback
  - 无可读 owner 时 kind=unknown, course_deleted=True
  - owner 跨 workspace 时 course_deleted=True
  - Course 已删除时 course_deleted=True, course_title=None
- 安全字段
  - AgentRunIdentity 只增加 code_language，不增加 provider/model/金额/代码/输出
  - code_language 只公开 python|java|cpp，异常历史值返回 null
  - FORBIDDEN_KEYS 扩展覆盖 source_code/stdin/stdout/stderr/compile_output/stem/options/answer_spec/rubric/feedback/answer_payload/observation/exit_code/MCP snapshot 字段
  - 递归 forbidden-key 测试覆盖 Practice 和 Code Lab Run
- Web 状态与响应式
  - safeRoleLabel 函数：未知 role 返回"其他运行"，不崩溃不空白
  - identityLabel 使用显式 switch，覆盖 course_generation/tutor/practice/code_execution/unknown 五种 kind
  - 筛选项增加 exercise_author/answer_grader/scientific_solution_grader/code_execution
  - 展开按钮增加 aria-expanded 和 aria-controls 关联详情区域
  - 错误码映射增加 Stage 4 practice/code/science 错误
  - Tool 标签增加 PracticeGeneration/PracticeGrading/CodeExecution/ScienceVerification
  - 样式沿用现有结构，未重做页面布局

## 验证

- 命令
  - `PYTHONPATH=apps/api .\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_agent_run_api.py apps/api/tests/test_stage3_eval.py apps/api/tests/test_stage4_eval.py`
  - `PYTHONPATH=apps/api .\.venv\Scripts\python.exe -m pytest -q apps/api/tests/test_practice_api.py apps/api/tests/test_mcp_orm_and_schema.py`
  - `cd apps/web && npm.cmd run lint && npm.cmd run build`
  - `git diff --check`
- 结果
  - API focused: 40 passed (23 agent_run + 10 stage3_eval + 7 stage4_eval)
  - Practice/MCP regression: 42 passed (18 practice_api + 24 mcp_orm_and_schema)
  - Web lint: 0 errors, 3 warnings (pre-existing, unrelated)
  - Web build: passed
  - git diff --check: passed
- 未运行及原因
  - Chrome 人工 smoke：按任务包规定由 Codex 接回后执行，GLM 不以截图或源码检查替代
  - 完整 test_practice_api.py 回归（非 identity/run 子集）：已运行全文件 18 passed
  - 真实 provider/Judge0/Wolfram/OCR：按任务包禁止调用

## 未解决问题

- 无。所有任务包规定的合同点已在自动化验证中覆盖。

## Codex 需要重点复核

1. _identity 中 Code Lab 分支的 Course/Lesson 回读逻辑：当 CodeLabRun.course_id 存在但 Course 已删除时，course_deleted=True 且不继续读 Lesson；确认这与 Spec 预期一致
2. course_id filter 新增的 Code Lab 子查询：使用 CodeLabRun.course_id 而非 CodeLabJob 直接关联，因为 Course FK 在 CodeLabRun 上；确认跨 workspace 边界正确
3. Web AgentRunSummary.role 从 AgentRunRole 改为 string：TypeScript 不再在编译期约束 role
   属于七种已知值，运行时由 safeRoleLabel 处理未知值；确认这符合 Spec
   “response role 保持字符串”的合同
4. 未知 role 的 identity kind 派生：当前 kind 由 owner 类型决定而非 role 字符串；一个 CourseGenerationJob owner + 未知 role 的 Run 会得到 kind=course_generation；确认这与 Spec "identity 从 owner 关系派生"一致
5. FORBIDDEN_KEYS 新增项：确认 exit_code、runtime、duration_ms、MCP snapshot 字段等加入禁止列表不误伤现有合法字段
