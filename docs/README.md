# 文档索引

## 当前指导文档

以下四份文档共同定义当前产品方向和开发方式：

- [学习平台蓝图](./LEARNING_AGENT_BLUEPRINT.md)
- [Self-host 开发路线](./SELF_HOST_DEVELOPMENT_ROADMAP.md)
- [数据库与部署计划](./DATABASE_AND_DEPLOYMENT_PLAN.md)
- [Agent 协作开发流程](./AGENT_COLLABORATION_PLAYBOOK.md)

实现交接的补充流程：

- [GLM 实现交接工作流](./GLM_IMPLEMENTATION_HANDOFF_WORKFLOW.md)

仓库级、可被 coding agent 自动加载的执行规则位于根目录 [AGENTS.md](../AGENTS.md)。

## 当前阶段

- [Platform Stage 0R：正确仓库基线重建](./00R-platform-baseline-reconstruction/README.md)
- [Stage 0R Spec](./00R-platform-baseline-reconstruction/specs/001-correct-repository-baseline-reconstruction.md)
- [产品分层 ADR](./00R-platform-baseline-reconstruction/adr/001-product-layer-and-dependency-boundaries.md)
- [现状评估与重新计划](./00R-platform-baseline-reconstruction/CURRENT_STATE_AND_REPLAN.md)
- [0R-A 依赖与验证基线](./00R-platform-baseline-reconstruction/DEPENDENCY_AND_VERIFICATION_BASELINE.md)
- [0R-B 原型合约盘点](./00R-platform-baseline-reconstruction/PROTOTYPE_CONTRACT_INVENTORY.md)
- [Platform Stage 1：Self-Host 平台壳](./01-platform-stage-1-self-host-shell/README.md)
- [Platform Stage 2：资料生命周期与引用检索](./02-platform-stage-2-material-lifecycle-and-citation-retrieval/README.md)
- [Stage 2 总结与 Stage 3 输入](./02-platform-stage-2-material-lifecycle-and-citation-retrieval/STAGE_2_SUMMARY_AND_STAGE_3_INPUTS.md)
- [Platform Stage 3：章节化学习与 Tutor（已完成）](./03-platform-stage-3-chapter-learning-and-tutor/README.md)
- [Platform Stage 4：练习、记忆与复习闭环（Slice 1/2/3/4/5 已完成并归档）](./04-platform-stage-4-practice-memory-and-review/README.md)
- [Platform Stage 5：可观测、系统验证与质量优化（顶层方向已通过 Gate）](./05-platform-stage-5-observability-system-validation-and-quality/README.md)

## Framework 指南

`framework/` 保存仍与 `hello_agents` 当前实现相关的技术指南。它们解释框架能力，不定义学习平台产品路线。

- [工具响应协议](./framework/tool-response-protocol.md)
- [上下文工程](./framework/context-engineering-guide.md)
- [Function Calling](./framework/function-calling-architecture.md)
- [异步 Agent](./framework/async-agent-guide.md)
- [流式输出与 SSE](./framework/streaming-sse-guide.md)
- [会话持久化](./framework/session-persistence-guide.md)
- [可观测性](./framework/observability-guide.md)
- [日志系统](./framework/logging-system-guide.md)
- [熔断器](./framework/circuit-breaker-guide.md)
- [子代理](./framework/subagent-guide.md)
- [Skills](./framework/skills-usage-guide.md)
- [自定义工具](./framework/custom_tools_guide.md)
- [文件工具](./framework/file_tools.md)
- [TodoWrite](./framework/todowrite-usage-guide.md)
- [DevLog](./framework/devlog-guide.md)

## 历史

- [Legacy 实现与仓库恢复总结](./history/LEGACY_AND_RECOVERY_SUMMARY.md)

旧阶段的详细计划、开发日志和恢复过程文档已由该总结替代。需要逐行追溯时使用 Git 历史，不再让过期文档占据当前文档入口。

## 维护规则

- 产品现状只写可由当前代码、测试或 Git 记录验证的事实。
- 路线图写阶段目标；Spec 写阶段内合同；ADR 写不可逆或跨模块决策。
- 已完成的短期计划在阶段总结中收敛，避免长期保留多份相互冲突的“当前计划”。
- Framework 指南与产品文档分开维护。
