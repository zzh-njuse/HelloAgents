# Stage 5 Part 1 Slice 1B OCR Review

日期：2026-07-28

## 结论

Slice 1B-1、1B-2、1B-3 的统一 OCR gate 通过。三项高置信问题已修复并完成
focused regression；其余报告项经上下文核对后判定为既有代码、白名单扫描造成的
误报，或登记为 Stage 5 Part 2 系统测试输入。

## 审查范围

- 数据模型、迁移、成本计算与数据库约束：11 个文件
- 五条业务写入链、记录器与链路测试：7 个文件
- Provider Call 安全读取 API、schema、service 与测试：6 个文件
- 合计：24 个文件，OCR 原始输出 100 条评论

OCR 使用独立白名单副本按风险边界串行 full-file scan。三个扫描块均完整结束；
第二块因外层脚本将自然语言中的 `timed out` 误判为扫描超时而报告停止，但 OCR
自身已完成 7/7 文件审查。确认无残留 OCR 进程。

## 采纳项

1. 四个 provider response parser 捕获空 `choices` 引发的 `IndexError`，并投影为
   各链既有稳定错误码。
2. timeout 事实同时保存 `status=timed_out` 与
   `error_code=provider_timeout`。
3. 读取 API 增加同时间戳按 ID 倒序、started 状态的空完成时间，以及 started
   状态完整 usage 成本投影测试。

排序测试初版错误地假设随机 UUID 与创建顺序一致；验收时已改为依据实际 ID
倒序生成期望值，未修改产品代码。

## 暂缓与排除

- `_next_ordinal` 的并发竞争风险：当前执行合同为同一 owner 单 worker，并有唯一
  约束兜底；并发反例与恢复行为登记为 Stage 5 Part 2 系统测试输入。
- 五条完整业务 orchestration 的 Provider Call 断言：按已批准验收决定，登记为
  Stage 5 Part 2 的明确输入，helper/recorder 测试不能替代。
- CORS、DocumentChunk 默认值、lease/MCP 等评论属于 Slice 1B 之外的既有代码。
- 路由 import、workspace active、limit、CNY server default 与 N+1 等评论，经真实
  仓库上下文和既有 Postgres/API 测试核对后不成立。

## 复验

- OCR 修复写入链与错误分类：11 passed
- 新增读取 API 边界：3 passed
- GLM handback 完整读取 API：30 passed
- GLM handback 本轮 focused suite：112 passed
- `git diff --check`：通过（仅既有行尾转换警告）

本轮不再次运行付费 OCR，避免无实质收益的 review loop。
