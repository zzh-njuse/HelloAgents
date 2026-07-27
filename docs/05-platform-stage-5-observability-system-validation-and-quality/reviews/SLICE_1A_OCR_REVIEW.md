# Stage 5 第一部分 Slice 1A：OCR Review

状态：完成

日期：2026-07-27

## 1. 范围与执行

真实 OCR 由用户在仓库外白名单副本上执行，使用三块顺序扫描：

| 分块 | 文件数 | 意见数 | Token | 用时 |
|---|---:|---:|---:|---:|
| API contract | 3 | 15 | 约 80,177 | 7m22s |
| API tests | 1 | 4 | 约 55,637 | 3m17s |
| Web | 2 | 9 | 约 100,965 | 7m45s |

三块均完整结束，没有零文件、非零退出、超时或预算截断。Raw 输出保存在
`reviews/raw/01-api-contract.txt`、`02-api-tests.txt` 和 `03-web.txt`。

## 2. 采纳项

结合 Spec、完整仓库和运行时事实，采纳 12 项高置信或低风险改进：

- 将 identity `kind` 和 `code_language` 收紧为已接受的 Literal 合同；
- CodeLabRun 软删除后不再回读语言和课程/课节身份；
- Practice grading course filter 在 Item、Attempt、Job 每层补 Workspace 条件；
- forbidden Tool 字段断言同时覆盖 Course 与 Tutor 详情；
- 扩大异常 Code Lab language 反例；
- 跨 Workspace owner 测试断言完整降级 identity；
- 角色/状态 filter 使用运行时类型守卫，不再依赖裸类型断言；
- 未知 role 使用 own-property 判断，避免原型属性被误当成已知角色；
- 筛选切换时清除旧列表并显示 loading，避免短暂展示不匹配结果；
- Course 列表请求支持 AbortSignal；
- 移除两处嵌套 job-type ternary；
- token/duration 使用显式 null 判断。

## 3. 排除与暂缓

以下意见不作为 Slice 1A 阻塞项：

- 认证/用户权限：当前 self-host Stage 尚未引入认证，且所有入口继续遵守既有
  Workspace 边界，不能由本 Slice 单独改变；
- cursor/offset：Spec 001 明确禁止 Slice 1A 新增分页；
- 未知 response role 改 Literal：与“历史/未来未知 role 必须可读”的合同冲突；
- inactive Workspace 改 409/422：既有产品采用 404 隐藏不可用对象，不在本
  Slice 改写；
- 全局上传幂等、RAG top-k、通用 error parser 和两个旧 API generic：来自
  `api.ts` 全文件扫描，均与本 Slice diff 无关；
- Code language 大小写归一化：合同要求只公开精确的
  `python|java|cpp`，异常历史值返回 null；
- 对所有 response schema 使用 `extra=forbid`、duration validator、硬删除 fixture：
  属于额外防御建议，现有服务白名单、FK/删除合同和 HTTP 负面测试已覆盖本 Slice；
- 列表 identity 的 N+1：是既有读取结构的真实性能风险，但当前上限为 20，修复需要
  批量加载设计和独立性能基线，暂缓到后续可观测/质量 Slice，不在本次临时重构。

## 4. 修正后复验

- Agent Run + Stage 3/4 eval：`41 passed`；
- Practice/MCP 回归：`42 passed`；
- Web lint：`0 errors`，保留 3 个既有 PracticePanel Hook warning；
- Web production build：通过；
- 浏览器 smoke：七角色筛选完整，`code_execution` 真实筛选只返回 5 条对应
  Run，390 x 844 视口无水平溢出；
- `git diff --check`：通过。

## 5. 结论

OCR 没有留下 High 或高置信 Medium 阻塞项。Slice 1A 的公开投影、安全字段、
Workspace 边界、Web 降级和响应式合同已满足，可以关闭实现与验收 Gate。
