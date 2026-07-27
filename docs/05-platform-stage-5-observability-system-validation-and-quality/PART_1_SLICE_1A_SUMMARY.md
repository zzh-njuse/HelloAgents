# Stage 5 第一部分 Slice 1A：完成总结

状态：已完成

日期：2026-07-27

## 实际完成

- Agent Run role filter 从 Stage 3 的三种扩展为当前七种稳定角色；
- Course Generation、Tutor、Practice 和 Code Lab 四类 owner 统一投影为五种
  identity kind；
- Code Lab 只公开精确白名单语言与可安全回读的 Course/Lesson 身份；
- 未知历史 role 保持可读并在 Web 降级为“其他运行”；
- Workspace、软删除、断链和敏感字段边界得到 HTTP 行为测试覆盖；
- 运行记录补全七角色筛选、五类 identity 文案、展开无障碍状态和移动响应式行为。

没有新增 ORM、migration、provider/model、人民币成本、聚合 dashboard、worker
或业务执行路径。

## 验证结果

- API focused/eval：`41 passed`；
- Practice/MCP 回归：`42 passed`；
- Web lint：0 errors；
- Web build：通过；
- Compose 与浏览器桌面/390 x 844 smoke：通过；
- 三块仓库外白名单 OCR：6 个文件全部审查，修正后无阻塞 finding；
- `git diff --check`：通过。

详细记录：

- [Codex 独立验收](reviews/SLICE_1A_CODEX_ACCEPTANCE_REVIEW.md)
- [OCR Review](reviews/SLICE_1A_OCR_REVIEW.md)

## 暂缓风险

- 当前列表 identity 仍按单条 Run 回读 owner 链；limit 20 下可接受，但应在后续
  可观测/质量工作中以查询计数和延迟基线判断是否需要批量加载；
- 现有 `PracticePanel.tsx` 保留 3 个与本 Slice 无关的 Hook warning；
- Slice 1A 不采集 Provider Call，也不计算或展示人民币成本。

## 下一阶段输入

Slice 1B 仍需单独评审 Provider Call 与人民币成本事实 ADR，包括：

- verified provider/model snapshot；
- token 缺失和估算 usage 的事实语义；
- CNY 价格快照与 unknown cost；
- 重试调用和业务 Run 的归属；
- 脱敏、保留期和迁移策略。

Slice 1B/1C 未因 Slice 1A 完成而自动批准。
