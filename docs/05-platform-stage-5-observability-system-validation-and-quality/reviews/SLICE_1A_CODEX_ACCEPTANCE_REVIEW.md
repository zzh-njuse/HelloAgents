# Stage 5 第一部分 Slice 1A：Codex 独立验收记录

状态：完成；自动化、浏览器 smoke 与真实 OCR 均通过

日期：2026-07-27

## 1. 验收范围

- 对照 Spec 001、前端概念和 GLM 实现任务包检查完整 diff；
- 检查公开 role/filter、identity、Code Lab 安全投影、Workspace 边界和禁止字段；
- 独立复跑 API focused、Practice/MCP 回归、Web lint/build；
- 使用当前 Compose 数据执行桌面与 390 x 844 移动视口浏览器 smoke；
- 不调用真实 provider、Judge0、Wolfram 或付费 OCR。

## 2. Codex 接回修正

独立检查后完成三项窄小修正：

1. 删除服务中的未使用 import/常量；
2. 删除前端并不存在于当前产品运行事实中的推测性 Stage 4 error/tool 映射，并简化
   重复图标分支，未知值继续使用既有安全降级；
3. 增加 Practice grading 断链 HTTP 回归，证明不会猜测 Course/Lesson 身份。

这些修正不改变已接受合同，也未扩展到 Slice 1B/1C。

## 3. 独立验证

### API

- Agent Run、Stage 3 eval、Stage 4 eval：`40 passed`；
- Practice API 与 MCP ORM/schema：`42 passed`；
- 接回修正后的 Agent Run focused：`24 passed`。

### Web

- ESLint：`0 errors`；保留 `PracticePanel.tsx` 中 3 个既有 Hook warning；
- production build：通过；
- 构建仅保留既有大 chunk warning。

### Compose 与浏览器

- 启动 Compose，并以当前源码重建 API 镜像；
- API、Postgres、Qdrant、Redis 和 Storage 在页面显示可用；
- 运行记录展示七个角色筛选项；
- `code_execution` 筛选真实命中 5 条 Code Lab Run，未混入其他 role；
- Code Lab identity 正确展示 `python|java|cpp`；
- 展开按钮的 `aria-expanded` 从 `false` 变为 `true`，`aria-controls` 指向实际详情；
- 详情仅显示安全 Tool 摘要；
- 390 x 844 视口下筛选控件和运行行无水平溢出。

## 4. OCR

`ocr review --preview` 证明普通 diff review 会把未知未跟踪的 `.tmp/` 和
`artifacts/` 一并纳入，共 325 个文件，违反本 Slice 的所有权和范围边界，因此
不得直接运行。

仓库外白名单副本已准备为 API 合同、API 测试和 Web 三块，逐文件哈希与当前
源码一致，三块 preview 和真实扫描分别发现 3、1、2 个文件。扫描无超时或预算
截断，采纳项已修复并复验；详见 [OCR Review](SLICE_1A_OCR_REVIEW.md)。

## 5. 当前结论

未发现阻塞发布的已知产品问题。自动化、Compose、浏览器 smoke 和 OCR 均已完成，
Slice 1A 可以关闭。提交和 push 仍需用户单独决定。
