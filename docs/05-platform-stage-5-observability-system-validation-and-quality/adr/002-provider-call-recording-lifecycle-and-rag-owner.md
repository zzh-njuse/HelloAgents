# ADR 002：Provider Call 记录生命周期与 RAG Owner

状态：已接受（2026-07-27）

日期：2026-07-27

## 背景

Slice 1B-1 已建立 Provider Call 和 CNY 价格快照，但尚无业务写入。Course、
Tutor 和 Practice 已有 AgentRun，RAG Answer 只有独立 RagAnswerTrace。低层
`call_provider` 不拥有 Workspace、owner 或数据库上下文，不能单独建立可靠归因。

如果各业务链分别拼装记录逻辑，会产生不同的状态、usage 和价格选择语义。如果
把 RAG 只记为 Workspace-only 调用，则无法证明某次费用属于哪个回答。

## 决策

1. 在拥有数据库和业务 owner 的 orchestration 边界复用一个共享 recorder；
   低层 HTTP adapter 不自行猜测 owner。
2. 每次真实外发请求单独记录；发送前建立 `started`，返回或受控异常后最终化。
3. 发送前错误不创建 Provider Call；Provider Call 约束未通过时不发送请求。
4. 正常业务事务内先 `flush` 再发送。本 Slice 不引入独立观测数据库或强制提交，
   也不擅自改变既有事务边界。
5. provider/model 取自实际调用配置，usage 只取 provider 明确报告值。
6. 价格选择为同 provider/model 在调用开始时间前最近生效的快照；无匹配时保持
   NULL，不估算。
7. migration `0025` 增加 RagAnswerTrace owner、Workspace 复合外键、owner
   互斥约束、RAG owner ordinal 唯一索引和删除级联。
8. AgentRun/Turn/Job/Trace 既有聚合继续保留，Provider Call 不反向重算它们。
9. Course、Tutor、Practice generation/grading 和 RAG Answer 在一个 Slice
   中一次接入，不再拆分子任务。

## 结果

优点：

- 所有 token 计费生成调用采用同一事实语义；
- repair/retry 不再被聚合字段覆盖；
- RAG Answer 获得可靠、可删除、Workspace 隔离的调用归因；
- 历史价格不依赖当前配置；
- 不改变现有生成与评分行为。

代价：

- 需要 migration `0025` 和跨五条调用链的集中回归；
- recorder 与业务事务同生共死，进程强杀可能没有持久化 `started`；
- 价格未人工维护时人民币成本仍为 unknown；
- 业务 owner 创建和 Provider Call 写入顺序必须满足数据库外键。

## 排除方案

- 四条业务域分别实现 recorder：语义易漂移，重复测试与返工成本高；
- 在低层 HTTP adapter 自动记录：缺少可靠 Workspace、owner 和 DB 生命周期；
- RAG 只使用 Workspace owner：无法归因到具体回答；
- 为 RAG 新建 AgentRun：扩大既有运行合同且不是本 Slice 所需；
- 使用当前价格回填：会改写历史含义；
- 为强杀场景立即引入独立事务/outbox：范围和行为风险过大，留给系统测试证据
  决定。

## 验证

以真实 orchestration + provider stub 验证调用次数、状态、usage、owner、phase、
价格选择和错误路径；以隔离 Postgres 验证 migration、复合外键、互斥、唯一性
和级联。不得调用真实 provider。
