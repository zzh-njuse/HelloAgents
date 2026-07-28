# Platform Stage 5：可观测、系统验证与质量优化

状态：顶层方向已通过人工 Gate；Slice 1A 已于 2026-07-27 完成实现、独立验收、
浏览器 smoke 和 OCR；Slice 1B-1/1B-2/1B-3 已通过独立验收和统一 OCR

Stage 5 的目标不是继续横向增加学习 capability，而是用可信运行事实和可重复
系统测试定位现有主链路的不稳定性，并据此改善课程、Tutor 和练习体验。Stage 4
已经完成并归档；其历史任务包只作为事实来源，不得直接继续执行。

## 评审摘要

本阶段建议分为三个工作部分：

1. 可观测与成本：先回答一次运行发生了什么、为何失败、耗时和消耗是多少。
2. CI 与系统测试：建立与真实用户主流程一致的纵向验证和稳定质量基线。
3. 最终优化：只根据前两部分产生的证据修复 Tutor、练习和课节体验，具体
   Slice 在事实盘点后另行评审。

三个部分是阶段级工作流，不代表各自只能有一个 Slice。每个正式 Slice 默认只
承担一个主要风险轴，并分别经过事实盘点、Spec、必要 ADR 和人工 Gate。

Postgres 备份恢复、Qdrant 重建 runbook、storage reconciliation、Redis/Qdrant
认证、容器非 root、端口收敛、反向代理和 HTTPS 不再属于 Stage 5 主范围。它们
作为明确暂缓项顺延到后续部署加固阶段，不视为取消或已经解决。

成本展示统一使用人民币（CNY）。Stage 5 不建设多币种、实时汇率、折扣、套餐
或账单系统；无法可靠换算时继续展示 token/调用量，并明确标记人民币成本未知。

## 用户价值

- 维护者能够根据真实 trace、eval 和系统测试定位 Tutor、练习与工具链问题。
- 概率性生成不再以单次成功作为稳定证据，而有固定样本、失败分类和趋势基线。
- 用户在课节、Tutor 和练习主路径中获得更稳定、清晰且可恢复的体验。
- 优化结果能够由回归证据证明，而不是依赖源码形状测试或主观观感。

## 当前入口

- [Stage 5 输入](STAGE_5_INPUTS.md)
- [Stage 5 三部分方向计划](STAGE_5_DIRECTION_PLAN.md)
- [第一部分事实盘点：可观测与成本](PART_1_OBSERVABILITY_COST_FACT_INVENTORY.md)
- [第一部分候选 Slice 计划](PART_1_CANDIDATE_SLICE_PLAN.md)
- [Slice 1A Spec：完整且安全的运行摘要合同](specs/001-complete-safe-run-summary-contract.md)（已接受）
- [Slice 1A 前端概念与状态矩阵](PART_1_SLICE_1A_FRONTEND_CONCEPT.md)（已接受）
- [Slice 1A GLM 实现任务包](PART_1_SLICE_1A_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 1A Codex 独立验收记录](reviews/SLICE_1A_CODEX_ACCEPTANCE_REVIEW.md)
- [Slice 1A OCR 执行交接](reviews/SLICE_1A_OCR_EXECUTION.md)
- [Slice 1A OCR Review](reviews/SLICE_1A_OCR_REVIEW.md)
- [Slice 1A 完成总结](PART_1_SLICE_1A_SUMMARY.md)
- [Slice 1B-1 Spec：Provider Call 与人民币成本事实基础](specs/002-provider-call-cost-foundation.md)（已接受）
- [ADR 001：独立 Provider Call 与人民币价格快照](adr/001-provider-call-and-cny-cost-facts.md)（已接受）
- [Slice 1B-1 GLM 实现任务包](PART_1_SLICE_1B1_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 1B-2 Spec：Provider Call 业务调用链接入](specs/003-provider-call-business-instrumentation.md)（已接受）
- [ADR 002：Provider Call 记录生命周期与 RAG Owner](adr/002-provider-call-recording-lifecycle-and-rag-owner.md)（已接受）
- [Slice 1B-2 GLM 实现任务包](PART_1_SLICE_1B2_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 1B-2 Codex 独立验收](reviews/SLICE_1B2_CODEX_ACCEPTANCE_REVIEW.md)
- [Slice 1B-3 Spec：安全 Provider Call 与人民币成本读取 API](specs/004-safe-provider-call-read-api.md)（已接受）
- [Slice 1B-3 GLM 实现任务包](PART_1_SLICE_1B3_GLM_IMPLEMENTATION_PACKET.md)
- [Slice 1B-3 Codex 独立验收](reviews/SLICE_1B3_CODEX_ACCEPTANCE_REVIEW.md)
- [Slice 1B 统一 OCR 修复任务包](PART_1_SLICE_1B_OCR_FIX_PACKET.md)
- [Slice 1B 统一 OCR Review](reviews/SLICE_1B_OCR_REVIEW.md)
- [Slice 1C Spec：Workspace 质量与成本读取体验](specs/005-workspace-quality-cost-read-experience.md)（已接受）
- [Slice 1C 前端概念与状态矩阵](PART_1_SLICE_1C_FRONTEND_CONCEPT.md)（已接受）
- [Slice 1C GLM 实现任务包](PART_1_SLICE_1C_GLM_IMPLEMENTATION_PACKET.md)
- [Stage 4 过程复盘](../04-platform-stage-4-practice-memory-and-review/STAGE_4_WORKING_RETROSPECTIVE.md)
- [Stage 4 Slice 5 完成总结](../04-platform-stage-4-practice-memory-and-review/SLICE_5_SUMMARY.md)
- [Self-host 开发路线](../SELF_HOST_DEVELOPMENT_ROADMAP.md)

后续经人工 Gate 后再建立 `specs/`、`adr/`、`reviews/` 和各 Slice 总结；本顶层
规划不替代这些交付物。

## 阶段不变量

- Postgres 继续持有产品事实；Redis 非权威，Qdrant 可重建，storage 持有文件
  字节事实。
- 现有 Practice artifact/schema、评分权威、重试预算和队列状态遵守 Stage 4
  Spec 005 / ADR 007；改变合同时必须重新经过 Spec/ADR Gate。
- 不为固定课程、题干、关键词、人工 smoke 输入或预期答案增加专用分支。
- 不以更多 mock、helper 测试或源码字符串检查替代真实编排和浏览器路径。
- 不借质量优化引入新的 MCP capability、自主多 Agent、认证、多租户或通用
  插件市场。
- trace、eval 和成本数据必须脱敏，不记录上传原文、完整 prompt、用户答案、
  Memory 正文、provider key、内部 URL 或绝对路径。

## 阶段级完成 Gate

- 至少一条代表性学习主路径可在 CI 或受控系统环境中跨 Web、API、worker、
  Postgres 和必要 adapter 重复运行。
- Tutor、普通练习和编程练习拥有固定小样本质量基线、稳定失败分类，以及明确
  的成功率、延迟和消耗口径。
- 关键系统测试具备反事实能力；破坏对应产品行为时测试能够失败。
- 最终优化项逐项关联可复现问题、基线和复验结果，不以一次人工成功关闭问题。
- 自动化、环境 Gate、真实 provider eval 和浏览器 smoke 分层报告，未验证项
  不冒充通过。
- 暂缓的备份恢复与部署安全风险在阶段总结和后续路线中保持可追踪。

## 开始实现前

第一部分 Slice 1A 与 Slice 1B 已完成；Slice 1C Spec 和前端概念已接受，可以
按正式 GLM 实现任务包执行。不得提前进入 Stage 5 第二部分。
