# Stage 5 第二部分候选 Slice 计划

状态：候选计划，等待人工 Gate

## 1. 拆分结论

第二部分建议只拆为两个 Slice：

1. Slice 2A：可重复的纵向系统测试与 CI 分层；
2. Slice 2B：Tutor、普通练习和编程练习质量基线。

该拆分避免把环境基础、业务纵向断言和概率性内容质量阈值放入同一个任务包，同时不再把每条业务链拆成独立小 Slice。

## 2. Slice 2A：纵向系统测试与 CI 分层

### 主要风险轴

现有测试无法证明真实 API、队列 worker、Postgres 和受控 adapter 能共同完成用户主流程。

### 交付范围

- 建立 Fast、Postgres、Controlled System、Browser、Compiler 和显式远程 Gate 的命令合同；
- 建立仓库级 CI workflow；
- 提供隔离的 Postgres/Redis/worker/provider-stub 系统测试环境；
- 先落地 Tutor 最小纵向路径；
- 在同一系统测试 harness 中覆盖五条完整业务 orchestration 的 Provider Call 断言；
- 让 Postgres 和关键编译器环境缺失成为明确失败，而不是静默 skip；
- 提供失败诊断摘要，并关联 AgentRun/ProviderCall 安全事实；
- 建立一个最小浏览器 smoke Gate，验证应用可进入并完成代表性用户动作。

### 不做

- 内容质量阈值；
- 真实付费 provider；
- Tutor/Practice 产品逻辑优化；
- 全量浏览器覆盖；
- 生产部署加固。

### 完成 Gate

- 干净环境可重复运行；
- Tutor 纵向路径真实跨 API、Redis worker、Postgres 和 provider stub；
- 五条链从完整业务入口产生正确 Provider Call；
- 关键反事实能够使测试失败；
- CI 对 pass、fail、skip、blocked 和 remote-not-run 分层报告；
- 普通 PR 零付费。

## 3. Slice 2B：固定小样本质量基线

### 主要风险轴

Tutor、普通练习和编程练习的概率性质量没有稳定基线，无法证明第三部分优化是否有效。

### 交付范围

- 为 Tutor、普通练习、Python/Java/C++ 编程练习建立小而固定的代表性样本；
- 区分结构有效、引用有效、可编译执行、评分一致、repair、失败分类；
- 输出成功率、失败分类、延迟、token 和人民币成本口径；
- 将离线 stub/recorded eval 与真实 provider eval 分开报告；
- 建立优化前基线快照，不提前修改产品行为；
- 生成第三部分问题清单，每项关联样本、失败类别和可复验命令。

### 不做

- 在基线建立过程中顺手修复 Tutor 或 Practice；
- 针对固定答案增加硬编码；
- 普通 PR 调用真实 provider；
- 把单次成功当作概率性基线；
- 改写 Practice artifact、评分权威或重试预算。

### 完成 Gate

- 三类学习能力均有固定样本和稳定分类；
- Python/Java/C++ 关键矩阵不静默 skip；
- 同一基线可在优化前后重复运行；
- 报告明确区分自动化、受控环境、真实 provider、人工 smoke 和未验证项；
- 第三部分可以根据证据选择优化顺序。

## 4. 执行顺序

```text
Part 2 事实盘点与人工 Gate
  -> Slice 2A Spec/必要 ADR
  -> Slice 2A 实现、系统 smoke、独立验收
  -> Slice 2B Spec
  -> Slice 2B 基线实现与报告
  -> Part 2 总结
  -> Stage 5 第三部分优化排序 Gate
```

## 5. Slice 2A 需要先决策的事项

在起草实现任务包前，Slice 2A Spec 至少需要锁定：

- CI 平台和 workflow 触发方式；
- provider stub 的进程边界与响应脚本格式；
- 系统测试是调用真实 RQ worker 进程还是受控单进程 worker；
- test-only Compose profile 和数据清理方式；
- 浏览器 Gate 使用的工具及首条用户动作；
- Python/Java/C++ backend 的固定方式；
- timeout、skip、blocked 和付费 Gate 的报告语义。
