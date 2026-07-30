# Spec 007：高风险工具调用与练习质量基线

状态：已于 2026-07-29 通过人工 Gate

日期：2026-07-29

## 1. 评审结论摘要

Slice 2B 不平均覆盖所有 Tutor 与 Practice 能力，而以人工 smoke 已暴露的失败分布
为依据，集中建立四类优化前基线：

1. Java 与 C++ 编程练习的生成、reference validation、浏览器作答与确定性评分；
2. scientific Practice 是否产生真正需要 Wolfram 的任务，以及请求、授权、调用、
   返回和最终 artifact 各阶段的成功率；
3. Practice 总题数提高后，生成预算、repair、专业题验证和最终发布的变化；
4. Tutor 对代码执行 MCP 与 Wolfram Cloud MCP 的必要调用、负对照和失败降级。

Python 作为稳定对照；普通选择题和普通问答只保留最小回归，不作为本 Slice 的主要
质量轴。

本 Slice 只建立可重复的基线、浏览器路径和失败分类，不修改 Practice artifact、
专业题数量、评分权威、生成预算、repair 次数、Tutor 工具预算或产品 prompt。

## 2. 背景

Stage 4 已接受并实现：

- `practice_artifact_v2` / `solve_utf8_string_v2`；
- 每 Set 最多一个 `coding` 或 `scientific` specialized item；
- Python、Java、C++ 受控代码执行；
- Wolfram Cloud MCP 的 `WolframAlpha` / `WolframContext` 白名单；
- Practice 科学验证与 Tutor Turn 级工具授权；
- 固定 repair、execution、MCP 和 provider 预算。

但人工 smoke 表明：

- 普通选择和问答不是当前主要失败源；
- Java、C++ 编程题成功率明显低于 Python，Java 风险最高；
- scientific Practice 经常没有出现可见 Wolfram 调用，但尚不能区分是题目过于简单、
  模型未请求工具，还是授权/readiness/MCP/结果处理失败；
- 总题数提高后更容易出现预算不足；
- Tutor 的核心未知不是普通回答，而是获得授权后是否真的调用代码或 Wolfram 工具，
  并在失败时诚实降级。

Slice 2A 已建立受控 Compose、provider stub、真实 worker、Postgres、Playwright 和
ProviderCall 事实。本 Slice 在该基础上建立风险加权的质量基线。

## 3. Goal / Constraints / Done When

| 项目 | 内容 |
|---|---|
| Goal | 在不改变产品行为的前提下，量化 Java/C++、Wolfram、Tutor 工具使用和高题数预算的真实失败位置与成功率 |
| Constraints | 不硬编码固定样本；不改变 Stage 4 Spec 004/005 与 ADR 006/007；普通 PR 零付费；远程 Gate 单独确认 |
| Done when | Java/C++ 浏览器路径、三语言 compiler matrix、Wolfram 调用漏斗、Tutor 双 MCP、题数预算曲线和真实远程基线均可重复报告 |

## 4. 基线样本

### 4.1 样本类别

固定样本集至少包含：

- 两份真正包含可执行目标和 evidence 的算法/编程课节；
- 两份真正包含数学、物理或通用化学计算目标的科学课节；
- 一个普通概念课节作为“不应强行生成专业题或调用工具”的负对照；
- Tutor 代码工具必要问题与不必要问题各至少一个；
- Tutor Wolfram 工具必要问题与不必要问题各至少一个。

样本可以是仓库内脱敏 eval fixture，但不能进入产品分支、生产 prompt 或运行时意图
识别。每个样本必须声明：

- 稳定 sample ID；
- lesson objective/evidence 类别；
- 请求模式和语言；
- `required | optional | forbidden` 工具预期；
- 预期用于判断哪一段合同，而不是固定自然语言答案。

### 4.2 Wolfram 必要性

Wolfram 样本必须区分：

- `required`：符号求解、较复杂积分/方程、单位或常量查询、需要外部计算复核的科学任务；
- `optional`：本地确定性规则可能已经足够；
- `forbidden`：简单算术或普通概念问题，调用工具不会增加价值。

`required` 是 eval 对样本教学/计算性质的标注，不是新增产品请求字段。若模型没有提出
工具请求，记录 `tool_request_missed`，不得把它误报为 MCP 连接失败。

## 5. 编程练习基线

### 5.1 当前请求合同

产品当前只支持：

- `item_count`：Set 总题数，`1..10`；
- `item_type_mode=require_coding`：Set 中至少一个 coding item；
- `code_languages`：coding item 的允许语言。

`Practice artifact v2` 同时规定每 Set 最多一个 specialized item。因此本 Slice 不得
增加或模拟“指定编程题数量”参数。

当 `item_count=1`、`require_coding` 且只允许一种语言时，该 Set 必须恰好包含一个
对应语言 coding item。总题数大于 1 时，基线记录实际题型分布，不把总题数冒充
编程题数量。

### 5.2 三语言矩阵

Python 是对照组；Java 与 C++ 是主要风险组。每个语言验证：

- artifact/schema/citation/target 与 v2 canonical contract；
- reference solution 编译与全部 public/hidden tests；
- starter 合法且不泄露答案；
- 正确解通过；
- 代表性错误解不能全通过；
- compile/runtime/timeout/output-limit/test-mismatch 分类；
- reference repair 是否发生及是否成功；
- ProviderCall、AgentToolCall、Job、Set、Attempt、Feedback 的最终事实；
- compiler/MCP/provider 私有正文未进入公开 API、日志和 eval report。

### 5.3 Java 与 C++ 浏览器路径

Java、C++ 各自必须有完整 Chromium Playwright 流程：

```text
系统测试 Workspace 与可执行课节
  -> Reader / Practice
  -> item_count=1
  -> require_coding
  -> 单一目标语言
  -> 用户授权代码执行
  -> 真实 Practice worker
  -> 受控 provider
  -> execution MCP + 固定测试 backend
  -> Set 发布并显示 coding item
  -> 提交代码
  -> Grading worker
  -> 确定性分数与反馈
  -> 运行记录显示 Practice generation / grading / Tool Call
```

至少覆盖一份正确答案和一种代表性错误结果。浏览器断言用户可见状态和安全投影，
不以 DOM 字符串检查替代 compiler/backend 事实。

Python 必须进入相同 API/compiler matrix，并可以复用参数化浏览器能力作为对照；
Java 与 C++ 浏览器路径不可因 Python 通过而省略。

## 6. 总题数与预算曲线

### 6.1 请求矩阵

在相同课节、难度、provider/model 和 artifact 版本下测试：

| 模式 | 总题数 |
|---|---|
| `general_only` | 1、3、5、10 |
| `require_coding` + 单一语言 | 1、3、5、10 |
| `require_science` | 1、3、5、10 |

`require_coding` / `require_science` 仍遵守每 Set 最多一个 specialized item；其余题必须
是普通题。若现有实现违反该合同，基线失败，不通过修改测试接受多个 specialized item。

### 6.2 记录口径

每次运行记录：

- 请求总题数与最终实际题数；
- 各 item type 数量和 coding language；
- plan、generation、repair 各 Provider Call 状态、usage 和 finish reason；
- reference/science verification 次数与状态；
- 权威 step count、MCP 调用数和 repair 次数；
- `practice_budget_exceeded` 或其他稳定失败发生的阶段；
- Set 是否原子发布，失败时是否零半成品；
- 总延迟、provider token 与已知人民币成本；
- 每题平均 token 只作为 eval 派生指标，不写回产品事实。

本 Slice 不提高预算，也不降低题数。第三部分根据曲线决定是否调整输出密度、分批生成
或重新评审预算合同。

## 7. Scientific Practice 与 Wolfram 调用漏斗

每个 scientific 样本按以下漏斗报告：

```text
sample_tool_expectation
  -> scientific item generated
  -> tool request planned
  -> authorization snapshot valid
  -> capability ready and schema matched
  -> MCP call attempted
  -> Wolfram result accepted
  -> science answer spec verified
  -> complete Set published
```

稳定分类至少包括：

- `tool_not_needed`；
- `tool_request_missed`；
- `authorization_missing`；
- `capability_unavailable`；
- `schema_drift`；
- `mcp_connection_failed`；
- `tool_result_invalid`；
- `scientific_reference_unverified`；
- `artifact_failed_after_tool_success`；
- `succeeded_with_wolfram`；
- `succeeded_without_wolfram`。

分类属于 eval/report，不新增 Job 状态。可以复用已有稳定错误码和安全 trace；不得保存
完整表达式、Wolfram 原文、题干、答案或内部 URL。

至少一条 scientific Practice Chromium 流程必须使用工具必要样本，验证生成、授权、
实际 Tool Call、用户可见 Wolfram 状态、作答/评分和运行记录。另有一个简单负对照，
验证无需工具时零调用。

## 8. Tutor 双 MCP 基线

Tutor 不以普通问答质量为主要轴，而验证：

1. code execution：必要样本请求 `run_code`，受控 backend 返回结果，Tutor 使用脱敏
   observation 回答；
2. science computation：必要样本请求 `WolframAlpha` 或 `WolframContext`，Tutor 使用
   observation 回答；
3. 两类负对照：即使用户授权，工具不增加价值时保持零调用；
4. 无授权、capability unavailable、schema drift、连接失败和全部 Tool Call 失败时，
   Tutor 显示稳定 limitation，不伪造结果。

代码与 Wolfram 各有一条完整 Chromium 路径。最终断言必须关联 Tutor Turn、
AgentRun、ProviderCall 与 AgentToolCall，且总 MCP/decision step 不超过既有预算。

## 9. Gate 分层

### 9.1 普通 PR：零付费

- scripted provider responses；
- fake execution backend；
- fake Wolfram MCP；
- 真实 API、Redis worker、Postgres、MCP client 边界和浏览器；
- Java/C++/Python 固定 compiler/runtime；
- 必需环境缺失为 `environment_failed`，不允许 skip。

fake backend 只证明协议、状态、UI 和失败分类，不能报告为真实 Judge0/Wolfram 已通过。

### 9.2 手动真实 Provider / Remote Gate

真实 Gate 与普通 PR 分离，并在每次运行前单独确认 provider、Judge0/Wolfram、样本量、
预计调用次数和可能成本。

真实 Gate 是 Slice 2B 正式验收的强制组成部分，不是可永久跳过的附加检查。在实现、
受控测试和浏览器 Gate 完成但尚未获准远程调用时，Slice 状态只能记录
`remote_not_run`，不得宣布 Slice 2B 完成或把真实能力标记为 passed。普通 PR 不承担
这项费用和远程波动；Slice 收尾必须由人工显式触发并核对真实结果。

沿用 Spec 005 已接受的编程候选样本量：

- 至少两份可执行课节；
- Python、Java、C++ 每种语言各生成 5 次；
- 每次只允许一种语言；
- 记录当前成功率，不因基线未达到 `4/5` 而降低门槛或修改样本。

scientific Practice、Tutor code MCP、Tutor Wolfram MCP 的必要样本各重复至少 5 次，
负对照各重复至少 3 次。真实调用结果单独标记；未运行时为 `remote_not_run`，并阻止
Slice 2B 正式收尾。

## 10. 报告

基线报告至少输出：

- sample、capability、language、mode、总题数和重复序号；
- 结构、reference/compiler、Tool 请求/调用、评分和最终 artifact 状态；
- 稳定失败阶段与错误类别；
- repair、provider、MCP 调用计数；
- latency、token、人民币成本或成本未知原因；
- controlled 与 real-remote 分层；
- 成功率分母、失败样本和可复验命令；
- 第三部分候选优化，不在本 Slice 直接实施。

报告中不得包含 prompt、课程原文、题干、答案、代码、tests、compiler/Wolfram 原文、
凭据、内部 URL 或绝对路径。

## 11. 反事实

至少证明：

- Java/C++ reference 无法编译时基线失败；
- 错误解意外全过时基线失败；
- `required` Wolfram 样本未提出 Tool 请求时归类为 request missed；
- Tool 已请求但 MCP 未调用时归类为 execution gap；
- fake Wolfram 返回无效 schema 时不会发布伪验证 artifact；
- capability 未 ready 时不接受新的强制专业题路径；
- 10 题发生预算不足时零半成品且阶段明确；
- 增加题数不能改变每 Set 最多一个 specialized item；
- 授权存在但 Tutor 负对照仍保持零调用；
- 工具失败时 Tutor 不声称已经运行或验证。

## 12. 非目标

- 新增“编程题数量”字段；
- 允许每 Set 多个 specialized item；
- 提高 provider、repair、MCP、step 或 wall-time 预算；
- 修改 Practice artifact/schema、评分权威、retry 或 Job 状态；
- 为固定样本增加关键词识别、固定答案或测试专用产品分支；
- 在建立基线时修复 Java/C++、Wolfram、Tutor 或高题数问题；
- 把真实 provider/Judge0/Wolfram 放入普通 PR；
- 扩展新的 MCP capability、动态 Tool discovery 或 WolframLanguageEvaluator；
- Firefox、WebKit、移动设备或视觉快照矩阵；
- 生产备份、恢复和部署加固。

## 13. 完成 Gate

### 自动化

- Java、C++ 各一条完整 Chromium 生成与评分路径通过；
- scientific Practice 的 Wolfram 必要路径与零调用负对照通过；
- Tutor code/Wolfram 必要路径和负对照通过；
- Python/Java/C++ compiler/runtime matrix 零 skip；
- 1/3/5/10 总题数矩阵可重复运行并输出预算曲线；
- Tool 请求、授权、实际调用、结果和最终 artifact 可独立分类；
- 破坏关键边界时测试真实失败；
- 普通 PR 零付费且不读取远程 secrets；
- Web lint/build、Compose、focused tests 和 `git diff --check` 通过。

### 人工与远程

- Java、C++ 浏览器路径各人工观察一次；
- scientific Practice 与 Tutor Wolfram 各观察一次 Tool Call 和一次负对照；
- 经单独人工确认后实际运行真实 provider/Judge0/Wolfram 基线；仅记录
  `remote_not_run` 不能通过 Slice 2B 完成 Gate；
- 查看报告，确认没有敏感正文且没有把总题数写成编程题数量；
- 确认第三部分优化顺序来自失败分布，而非单次印象。

## 14. 待人工 Gate

1. 是否接受 Slice 2B 只聚焦 Java/C++、Wolfram、Tutor 双 MCP 和总题数预算，不平均
   覆盖稳定的选择题/普通问答？
2. 是否接受 Java 与 C++ 都必须有完整 Chromium 生成、作答、评分和运行记录路径？
3. 是否接受 Python 作为稳定对照，但仍进入 compiler/API 和真实 provider matrix？
4. 是否接受当前只能指定 Set 总题数，`require_coding` 不等于指定编程题数量，并继续
   遵守每 Set 最多一个 specialized item？
5. 是否接受总题数矩阵为 `1/3/5/10`，但本 Slice只测量预算，不提高上限？
6. 是否接受 Wolfram 基线必须先区分“题目不需要/模型未请求”和“MCP 请求后失败”？
7. 是否接受 scientific Practice、Tutor code、Tutor Wolfram 都建立工具必要样本和
   零调用负对照？
8. 是否接受普通 PR 只用受控 provider/fake backend，真实 provider/Judge0/Wolfram
   继续作为单独付费/远程 Gate？
9. 是否接受真实编程基线沿用每语言 5 次，工具必要样本各 5 次、负对照各 3 次，
   每次执行前再确认成本？
10. 是否接受 Slice 2B 只交基线与第三部分输入，不在本 Slice 修复失败或改变合同？

以上 10 项已于 2026-07-29 获人工接受。

第 8 项接受时增加强制解释：普通 PR 继续使用受控 provider/fake backend，保证零付费
和确定性；但 Slice 2B 这种大块更新在正式收尾前必须完成真实 provider、Judge0 与
Wolfram Cloud MCP 验收。`remote_not_run` 只表示尚待人工触发，不能作为 Slice 完成
状态。
