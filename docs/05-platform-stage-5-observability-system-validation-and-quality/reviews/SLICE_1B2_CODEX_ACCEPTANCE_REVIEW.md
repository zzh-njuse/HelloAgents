# Slice 1B-2 Codex 独立验收

状态：通过（含一项人工接受的验证豁免）

日期：2026-07-27

## 范围

验收 Provider Call 对 Course generation、Tutor、Practice generation、
Practice grading 和 RAG Answer 的统一接入，以及 migration `0025`、共享
recorder、RAG owner、价格快照选择、错误分类和 phase。

未运行 OCR；按已接受策略，1B-1/1B-2/1B-3 完成后统一执行。

## 主要验收过程

独立检查先后发现并推动修复：

1. AgentRun owner 可跨 Workspace 错绑；
2. 调用可绑定其他 provider/model 的价格快照；
3. RAG `_generate` 三元组与 recorder 二元组合同不兼容；
4. timeout 被记录为 failed；
5. repair phase 标记错误；
6. 异常正文可能进入 error code；
7. budget failure 被错误分类为 canceled。

最终实现使用数据库复合外键保护 Workspace 和价格绑定；timeout 可沿
`__cause__`/`__context__` 安全识别；错误码为稳定低基数集合；repair phase
由实际调用点显式传入。

## 独立复验

Codex 实际复跑：

```text
test_provider_call_recorder.py
test_provider_call_chain_behavior.py
test_provider_cost_calculator.py

86 passed in 114.15s
```

`git diff --check` 通过。

GLM 另报告 ORM/calculator、Postgres migration/外键/删除和 AgentRun API
相关回归通过。Codex 未重复运行这些检查，以控制额度和重复成本。

## 人工接受的有限豁免

`test_provider_call_chain_behavior.py` 使用真实 HTTP helper、provider stub 和共享
recorder，但未调用 `execute_generation`、`execute_grading`、
`execute_tutor_turn`、`answer_question` 等完整业务 orchestration 入口。

2026-07-27 人工接受：

- Slice 1B-2 不再因此返工；
- 当前静态接入核对、focused tests 和既有回归作为本 Slice 验收证据；
- “完整业务 orchestration Provider Call 断言”必须进入 Stage 5 第二部分
  CI/系统测试，覆盖五条链的 owner、phase、ordinal、usage、调用次数、timeout
  和 repair；
- 第二部分不得再以直接调用 recorder/helper 的测试替代该纵向验证。

## 结论

Slice 1B-2 通过独立验收，可以进入 Slice 1B-3。上述有限豁免是后续强制输入，
不是“已由完整系统测试证明”。
