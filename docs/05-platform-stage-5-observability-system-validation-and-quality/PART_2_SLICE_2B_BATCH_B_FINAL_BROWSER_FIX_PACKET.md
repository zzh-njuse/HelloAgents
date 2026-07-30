# Stage 5 Part 2 Slice 2B Batch B 最终浏览器修正任务包

## 1. 人工批准

人工批准最后一次窄扩围：

1. 修改 `apps/web/src/styles.css`，修复练习左栏溢出后被 sticky Tutor 截获点击；
2. 修正 Tutor Playwright 对 grounding 合同无效文本的断言；
3. 完成全部 Batch B 浏览器 Gate。

不得修改 Tutor generation、worker、API、schema、生成/评分/预算/prompt 或 grounding 合同。

## 2. 已确认根因

### 2.1 Practice

练习面板和 selector 已正常工作。真实失败是 `.reader-with-tutor` 两列网格内，左侧 `.reader`
及其内部内容缺少完整收缩约束；练习表单溢出到右栏下方，后绘制的 sticky TutorPanel 截获
Java/C++ checkbox 与“生成练习”按钮点击。

这是产品布局缺陷，不允许通过以下方式绕过：

- 切到“练习记录”隐藏 Tutor；
- Playwright `force: true`；
- JavaScript 直接触发 click；
- 调整测试视口逃避；
- 隐藏或移除 Tutor；
- 直接 API 提交。

### 2.2 Tutor

SSE/轮询修复已经生效：Turn succeeded、工具计数和 observation 块均已到达 UI。

失败断言等待 `"Binary search halves"`，但该 `direct_answer` 携带 stub 伪造的 `"e1"`；
course-scope ledger 不允许该引用，产品 grounding 校验正确丢弃事实块。不得修改
`tutor_generation.py` 或放宽引用校验。

浏览器 Gate 应断言与目标能力直接相关的合法事实：

- code required：code observation + `代码 1 次`；
- Wolfram required：science observation + `科学 1 次`；
- negative：Turn succeeded + 对应调用计数为 0；
- 必要时同时查询受控 fake counter。

## 3. 允许文件

- `apps/web/src/styles.css`
- `apps/web/e2e/practice-tools.spec.ts`
- `apps/web/e2e/tutor-tools.spec.ts`
- 必要时 `apps/web/playwright.config.ts`（只修真实配置问题）
- Batch B handback

其他文件不得修改。发现需要扩大范围时停止。

## 4. CSS 修复要求

- 为 `.reader-with-tutor` 的左侧 grid item、`.reader`、`.reader main` 和必要的练习容器补充
  `min-width: 0` / 合理 overflow 或等价约束；
- 保持桌面两栏，Tutor sticky 行为不变；
- 860px 以下保持现有单列响应式；
- 表单、语言 checkbox、按钮、CodeMirror 和长文本不得伸入右栏；
- 不使用任意固定宽度把问题转移到其他分辨率；
- 不增加 z-index 让左栏反过来覆盖 Tutor；
- 不隐藏或裁掉用户必须操作的内容；
- 不改变现有视觉主题或做无关样式清理。

至少核对桌面 `1280x720`、宽桌面 `1600x900` 和窄屏 `820x900`：

- 无重叠；
- 所有文本与控件在所属栏内；
- Java/C++ checkbox 和生成按钮可正常点击；
- 窄屏 Tutor 位于内容下方且不遮挡。

## 5. Practice 浏览器合同

修正语言选择：

- 生成 Java 前确保 Python/C++ 未选，只选择 Java；
- 生成 C++ 前确保 Python/Java 未选，只选择 C++；
- 不依赖默认选中状态；
- 生成后验证 artifact 显示语言与目标完全一致。

完整路径仍必须经过 UI：

- 生成；
- 填写 CodeMirror；
- 交卷；
- 评分终态；
- 自动测试反馈；
- 运行记录。

## 6. Tutor 浏览器断言

### code required

- Turn succeeded；
- `Running the small program confirmed the observed behaviour.` 可见；
- `代码 1 次` 可见；
- fake execution counter 精确符合场景合同。

### code negative

- Turn succeeded；
- `代码 0 次` 可见；
- fake execution counter 为 0；
- 不要求无效 direct_answer。

### Wolfram required

- Turn succeeded；
- `The symbolic result was verified by the computation tool.` 可见；
- `科学 1 次` 可见；
- fake Wolfram counter大于 0，并符合精确场景合同。

### Wolfram negative

- Turn succeeded；
- `科学 0 次` 可见；
- fake Wolfram counter为 0；
- 不要求无效 direct_answer。

断言文本只验证 test stub 的受控 observation，不进入产品逻辑。

## 7. 验证

先执行：

```powershell
cd apps/web
npm.cmd run lint
npm.cmd run build
cd ../..
```

再完整执行：

```powershell
.\scripts\browser-test.ps1
```

必须全部 9 项 `passed`、0 failed、0 skipped。不得只跑 grep。

复跑：

```powershell
.\scripts\system-test.ps1
bash -n scripts/browser-test.sh
bash -n scripts/system-test.sh
git diff --check
```

确认所有本 Slice Compose 容器、网络和卷均已清理。

## 8. Handback

更新 `PART_2_SLICE_2B_BATCH_B_GLM_HANDBACK.md`，补充：

- CSS 根因与实际规则；
- 三种 viewport 的无重叠检查；
- Java/C++ 单语言选择证据；
- 四条 Tutor 合法 observation/计数断言；
- 完整 9 项浏览器结果；
- system regression、lint/build、脚本语法、diff check；
- 残留资源检查；
- `remote_not_run`；
- 未 OCR、未 commit/push、未进入第三部分。

完成后停止交回 Codex。
