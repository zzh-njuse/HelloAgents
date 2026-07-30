# Stage 5 Part 2 Slice 2B Batch B 浏览器验收修正任务包

## 1. 人工批准与目标

人工已批准一个窄产品修复，用于关闭 Batch B 浏览器 Gate。仅处理：

1. Practice Playwright 下拉选项定位错误；
2. Tutor Turn 在 SSE 建立前完成时，页面永久停留在旧状态；
3. Playwright 全局 30 秒超时早于测试内部 40 秒等待。

不得借此修改生成、评分、预算、API、schema、prompt 或工具决策行为。

## 2. 已复现事实

Codex 在隔离 Compose 中完成 seed，并独立复现：

### 2.1 Practice

练习面板实际正常渲染。失败发生在：

```text
selectOption({ label: lessonName.source })
```

`lessonName.source` 为 `Coding Tools`，但 seed 选项包含随机后缀，例如
`Coding Tools b27f54`。`selectOption.label` 是精确字符串，不是正则匹配，因此一直等待不存在的选项。

### 2.2 Tutor

Tutor worker 在约 1.3 秒内成功完成；stub 计数为 2，execution 计数为 1，但浏览器不显示答案。

产品 `TutorPanel` 只在 React 已观察到 active Turn 后建立 EventSource。如果 worker 在 EventSource
建立前已完成，完成事件会丢失；页面没有兜底刷新，因而永久保留 queued/running 快照，刷新整页后才显示终态。

### 2.3 Timeout

Playwright config 的 test timeout 为默认 30 秒，但 spec 内使用 40 秒可见性等待。测试会被外层
30 秒提前终止，内部 40 秒永远不可能生效。

## 3. 允许修改

- `apps/web/src/app/TutorPanel.tsx`
- `apps/web/e2e/practice-tools.spec.ts`
- `apps/web/e2e/tutor-tools.spec.ts`
- `apps/web/playwright.config.ts`
- 必要的 Web 现有测试文件（仓库没有 test runner 时不得安装）
- Batch B handback

不得修改其他产品代码。若发现需要扩大范围，停止并报告。

## 4. Tutor 终态兜底合同

为 active Turn 增加 EventSource 之外的有界刷新兜底：

- 进入 active 状态后立即刷新一次，再以短间隔刷新；
- 从 `fetchTutorSession(workspaceId, sessionId)` 读取权威状态；
- 到达 succeeded/failed/canceled/queue_failed 等终态后停止；
- session、turn、workspace 改变或组件卸载时停止；
- 旧请求晚到不得覆盖新 session/turn/workspace 状态；
- EventSource 继续保留，轮询只是丢事件兜底；
- 网络瞬时失败不得清空现有内容，也不得制造无限错误提示；
- 使用有界次数或明确 wall-time，超出后停止，不无限请求；
- 不使用固定答案、测试场景判断或测试专用产品分支；
- 不要求用户刷新页面；
- 不改变 API、Turn 状态或 worker 行为。

实现时优先复用现有 active 判定与 `fetchTutorSession`。使用 request sequence、AbortController
或等价机制阻止旧响应写入。

## 5. Practice selector 修正

- 从“练习课节”下拉框读取真实 option；
- 使用正则匹配可见 option 文本；
- 获取该 option 的 value 后调用 `selectOption(value)`；
- 匹配必须唯一；零个或多个匹配均使测试立即失败并输出候选文本；
- 不硬编码随机后缀，不按 option index 猜测；
- helper 的类型使用 `Locator`，不得把 Locator 标为 `Page`。

## 6. Playwright timeout

- 为 worker/MCP 浏览器 spec 设置明确且一致的总超时，例如每项 90 秒；
- 内部终态等待必须小于总超时；
- 不通过无限增大 timeout、重试或固定 sleep 隐藏 UI race；
- 保留 Chromium only、单 worker、失败 trace/screenshot；
- CI 预计耗时必须保持在 job timeout 内。

## 7. 必须通过的浏览器路径

受控 Compose 中全部通过，零 skip：

- Java Practice：生成、作答、评分、运行记录；
- C++ Practice：生成、作答、评分、运行记录；
- scientific Practice Wolfram required；
- scientific Practice negative，已授权但零调用；
- Tutor code required；
- Tutor code negative，已授权但零调用；
- Tutor Wolfram required；
- Tutor Wolfram negative，已授权但零调用；
- 既有 `app-shell.spec.ts` Tutor smoke。

不得用 API 提交代替浏览器作答，不得 seed 已完成 Set，不得把系统测试替代浏览器 Gate。

## 8. 验证

先运行 Web：

```powershell
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
```

再运行完整浏览器脚本：

```powershell
.\scripts\browser-test.ps1
```

不得只跑单个 grep 后宣称全部通过。

然后复跑受控系统测试，证明 UI 修复未影响系统合同：

```powershell
.\scripts\system-test.ps1
git diff --check
```

检查测试项目容器、网络和卷全部清理。`.sh` 至少运行 `bash -n`；若有 Linux 环境则实跑。

## 9. Handback

更新：

`PART_2_SLICE_2B_BATCH_B_GLM_HANDBACK.md`

必须补充：

- 三个根因及对应修正；
- Tutor 轮询终止、取消和晚到响应防线；
- option 唯一匹配方式；
- 实际 Playwright 每项与完整套件结果；
- system regression、lint/build、diff check；
- 残留资源检查；
- `remote_not_run` 仍阻止 Slice 收尾；
- 未 OCR、未 commit/push、未进入第三部分。

完成后停止，交回 Codex。
