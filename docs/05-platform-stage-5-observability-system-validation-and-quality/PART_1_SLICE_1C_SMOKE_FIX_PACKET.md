# Stage 5 Part 1 Slice 1C 人工 Smoke 修正包

状态：可执行

日期：2026-07-28

## 问题

人工 smoke 发现质量摘要显示“摘要读取失败”。API 日志与直接 HTTP 回读均证明
endpoint 返回 200 和合法 JSON；同一页面却在短时间反复请求
`quality-cost-summary` 和 `agent-runs`。

根因是 `QualityCostPanel` 的 effect 依赖环：

```text
summary 改变
  -> refreshFailedRuns callback 改变（依赖 summary）
  -> refresh callback 改变
  -> useEffect cleanup/重新执行
  -> abort 当前请求并再次 setSummary(null)
  -> summary 再次改变
```

这会造成请求风暴、互相 abort 和不稳定的 error/loading 投影。

## 修复要求

1. 摘要状态不得成为启动摘要请求 effect 的间接依赖。
2. 将摘要请求和异常列表请求的生命周期解耦，或让一次协调函数显式取得摘要
   `from/to` 后再传给异常列表函数。
3. `refreshFailedRuns` 不得闭包依赖整个 `summary` 对象；时间边界应通过参数传入
   或由独立稳定状态保存。
4. 切换 window/role/status/business type 时：
   - 每类请求只发出预期的有限次数；
   - 旧请求可以 abort，但 abort 不得显示为读取失败；
   - 新摘要成功后稳定留在页面，不再循环清空；
   - 异常列表继续按服务端返回的 `from/to` 过滤。
5. 手动刷新同时刷新两块，但一块失败不能清空另一块已经成功的数据。
6. 自动化锁定请求次数。仓库无组件测试 runner时，不安装依赖；至少把可测试的
   请求协调逻辑抽为纯 helper 并覆盖，浏览器 smoke 必须检查 Network 不再持续
   重复请求。

## 说明

截图所选 Workspace 是 `test`，而此前几十条记录位于另一个
`课程生成测试` Workspace。质量页的“最近异常运行”只显示 failed/canceled，
不是全部运行，因此 `test` 下显示一条异常本身不是 bug。摘要 API 对该 Workspace
的真实返回为 7 个 Run，其中 1 个 failed。

## 验证

```powershell
Push-Location apps/web
npm.cmd run lint
npm.cmd run build
Pop-Location
git diff --check
```

完成后更新 Slice 1C handback，记录 smoke 根因与修复。不要 commit、push、OCR
或进入 Stage 5 第二部分。
