# Platform Stage 5 输入

状态：顶层方向 Gate 已通过；第一部分事实盘点和 Slice 1A 已完成；Slice 1B/1C
尚未批准

日期：2026-07-27

## 可继承的产品事实

- Stage 1 至 Stage 4 已建立 workspace、资料、课程、Tutor、练习、掌握度、
  Memory、受控代码执行和 Wolfram 科学工具的产品主路径。
- Postgres 已持有 Agent Run、Tool Call、异步 Job 和学习业务权威事实；现有
  trace 足以支持最小审计，但尚未形成统一质量、成本和运维视图。
- Stage 3/4 已有固定离线 eval、focused tests、Web build、OCR 和真实浏览器
  smoke 经验，可作为 Stage 5 事实来源，但历史通过记录不能替代当前复跑。
- Stage 4 Practice artifact contract v2、canonical harness、有限 repair、
  确定性评分和稳定错误码已经建立，后续修复不得静默改写其权威边界。
- Tutor、Practice、execution 和 science capability 已存在不同 provider、
  worker、预算和失败路径，统一观测必须保留这些业务差异。

## Stage 4 已确认的过程问题

1. 后期 Slice 同时叠加多个独立风险轴，任务包和验收范围过大。
2. 单元和 focused tests 数量不少，但跨 Provider、编排、数据库、外部工具和
   Web 的系统测试不足。
3. 真实 smoke 进入偏晚，导致工具链、预算、状态投影和交互问题在后期集中暴露。
4. 部分测试只检查源码字符串、复制产品判断逻辑或绕过真实执行入口，不能证明
   用户主流程。
5. 编译器在 PATH 中不代表工具链健康，Docker test image 也没有稳定承担
   Java/C++ compiler Gate。
6. 概率性 Provider 功能缺少统一的小样本成功率、失败分类、延迟和成本基线。

## 当前优先问题

### 可观测与成本

- Run、Tool、Job 和 eval 当前分别记录了什么，哪些字段可安全统一，哪些业务
  差异必须保留？
- Tutor、Practice generation/grading、代码执行和科学工具的调用、重试、
  延迟、token 与成本如何按 attempt 和业务对象归因？
- provider/model 与人民币单价快照如何版本化；缺少可靠人民币单价时如何只展示
  usage 并标记成本未知？
- 失败分类能否区分产品验证、预算、队列、provider、编译执行、外部工具和用户
  输入错误？
- 指标如何避免高基数、敏感正文、内部连接信息和不可控存储增长？

### CI 与系统测试

- 哪一条最小纵向路径能代表 Course Reader、Tutor、普通练习和编程练习的真实
  行为，而不要求每次调用付费 provider？
- 如何分开单元、组件、编排、数据库、环境、浏览器和真实 provider eval？
- Python/Java/C++ compiler/runtime 如何固定版本、禁止关键 matrix 静默 skip，
  并与 Judge0 真实边界区分？
- 哪些测试需要真实 Postgres、Redis、worker 和浏览器，哪些可以使用受控
  fake/recorded observation？
- 如何为关键测试增加反事实检查，避免测试复制生产逻辑后自我证明？
- 如何在 CI 时长、可重复性和外部成本之间建立分层 Gate？

### 最终优化

- Tutor 不稳定应按检索、上下文选择、教学 Skill、provider 输出、结构验证、
  工具调用和 Web 投影中的哪一层分类？
- 普通题、Python/Java/C++ 编程题和科学题分别有哪些可重复失败；生成成功率、
  reference validation、repair、预算和评分如何测量？
- 编程相关优化是否需要改变 artifact/schema、canonical contract、评分权威或
  重试预算；若需要，必须先重新进入 Spec/ADR Gate。
- 课节页面的文本排版、代码块、公式、引用、长内容阅读和响应式交互有哪些具体
  可复现问题？
- 哪些问题属于质量修复，哪些是新能力或大范围重设计，必须移出 Stage 5？

## 暂缓但不得遗失

- Postgres backup/restore。
- Qdrant rebuild runbook 与 storage reconciliation。
- Redis/Qdrant auth。
- 容器非 root、默认端口、反向代理和 HTTPS hardening。
- 正式发布与生产运维手册。

这些事项顺延至后续部署加固阶段。Stage 5 如为系统测试需要调整 test-only
镜像或 CI 环境，不代表已经完成生产部署加固。

## 首轮事实盘点必须回答

1. 当前 Run、Tool、Job、usage、latency、eval 和 error 数据的完整来源矩阵。
2. Tutor、普通练习和编程练习各自最小可重复失败样本与当前成功率基线。
3. 一条跨 Web、API、worker、Postgres 和 adapter 的代表性系统路径。
4. 当前 CI/test image、编译器、Compose 和浏览器环境的可重复性缺口。
5. 哪些现有测试真实经过生产入口，哪些只是局部、source-inspection 或 mock。
6. 第一个小 Slice 应只解决哪个风险轴，其变更失败时如何回退。

上述问题的第一轮结论见
[第一部分事实盘点](PART_1_OBSERVABILITY_COST_FACT_INVENTORY.md)；候选拆分见
[第一部分候选 Slice 计划](PART_1_CANDIDATE_SLICE_PLAN.md)。

## 顶层人工 Gate（已通过）

- 2026-07-27 已接受 Stage 5 三部分方向及备份恢复、部署安全的顺延。
- 已接受“一个 Slice 一个主要风险轴”和分层验证作为本阶段强制执行方式。
- 已接受成本展示统一使用人民币；不建设多币种、实时汇率、折扣、套餐或账单
  系统。
- 首个 Slice 开始前，单独接受其 Spec、必要 ADR、系统测试路径、成本和未验证
  项；本文件不自动批准实现。
