# Stage 5 第二部分事实盘点：CI 与系统测试

状态：第一轮草案，等待人工 Gate

日期：2026-07-28

## 1. 评审摘要

当前仓库拥有数量较多的 API、ORM、worker、Postgres、eval 和修正回归测试，但尚未形成可持续执行的 CI 分层，也没有一条能够证明 Web、API、真实队列 worker、Postgres 和受控 adapter 共同工作的自动化纵向路径。

最明显的缺口不是“测试数量不足”，而是：

1. 仓库没有项目级 GitHub Actions workflow；
2. 许多业务测试直接调用 service/helper，并通过 monkeypatch 替换队列、provider、检索或外部工具；
3. Postgres 测试在环境不可达时会 skip，当前没有必定提供 Postgres 的 CI Gate；
4. Web 只有 lint/build，没有前端单元测试或浏览器自动化测试运行器；
5. Compose 有完整服务拓扑，但尚无 test-only profile 驱动真实 worker 和纵向断言；
6. Python/Java/C++ 执行能力依赖外部 execution backend，当前 test image 没有明确的三语言环境 Gate。

因此，第二部分不能通过再增加一批局部 mock 测试完成。首要任务应是建立受控、无付费 provider 的真实 orchestration 与环境 Gate。

## 2. 当前可复用基础

### 2.1 服务拓扑

根 `docker-compose.yml` 已包含：

- Web；
- API；
- Postgres 16；
- Redis；
- Qdrant；
-通用 worker；
- Practice worker；
- Code Lab worker；
- MCP execution adapter；
- capability probe；
- reconciler；
- `api-test` test target。

这些服务可以作为系统测试环境的起点，但当前 Compose 没有：

- 独立系统测试 runner；
- 受控 provider stub；
- 受控 execution backend；
- 明确的 test profile 启停和清理合同；
- 纵向测试结果或诊断 artifact。

### 2.2 已有测试层

| 层级 | 当前事实 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| unit/domain | calculator、validator、artifact、skill 等测试较多 | 局部纯逻辑 | 产品纵向流程 |
| API/component | TestClient + SQLite/测试 Session | HTTP 合同和局部 ORM 行为 | 真实 Postgres、Redis worker |
| orchestration-like | service/worker + monkeypatch provider/retrieval | 业务分支与稳定错误码 | 真实队列投递和完整进程边界 |
| Postgres | 多个 throwaway database 测试 | FK、migration、聚合和隔离 | CI 中必定执行 |
| environment | Compose build/readiness、人工 smoke | 本机环境可启动 | 自动反事实和持续 Gate |
| browser | 人工浏览器 smoke | 真实交互可用性 | 可重复的浏览器回归 |
| real-provider eval | Stage 3/4 离线或人工经验 | 特定环境下的内容质量 | 普通 PR 的无成本稳定 Gate |

### 2.3 第一部分留下的强制输入

第二部分必须补齐五条完整业务 orchestration 的 Provider Call 断言：

1. Course generation；
2. Tutor；
3. Practice generation；
4. Practice grading；
5. RAG Answer。

每条链需要从公开业务 service 或真实 orchestration 入口进入，最终从数据库读取 `ProviderCall`，断言：

- owner；
- phase；
- ordinal；
- usage；
- provider 调用次数；
- timeout/failed/canceled 分类；
- repair 路径；
- workspace 隔离。

不得再以直接调用 recorder、provider wrapper 或低层 helper 代替。

## 3. 当前 CI 缺口

### 3.1 没有仓库级 workflow

当前没有 `.github/workflows`。因此：

- lint/build/test 没有远端必过状态；
- Postgres 可用性没有固定环境；
- skip 数量没有集中报告；
- 付费或远程 Gate 没有显式区分；
- 无法声明某个提交已通过统一 CI。

### 3.2 skip 可能冒充通过

多项 Postgres 测试会在本地数据库不可达时 skip。这对开发机是合理降级，但在受控系统 Gate 中必须视为环境失败，不能作为绿色结果。

### 3.3 Web 自动化空缺

`apps/web` 当前只有 lint/build，没有 Vitest/Jest/Playwright 测试入口。Slice 1C 的请求竞态只能依赖人工 smoke，说明浏览器层尚未形成回归能力。

### 3.4 adapter 和编译器环境不固定

Compose 中的 MCP execution adapter 仍依赖 `EXECUTION_BACKEND_URL`。它不能证明 Python/Java/C++ 编译执行链在干净环境可用，也不能把 backend 缺失与产品行为失败明确分开。

### 3.5 测试命名反映历史修正，不等于稳定分层

当前存在较多 `correction_*`、`slice4_*`、`slice5_*` 测试。它们是重要回归事实，但不适合作为长期 CI 分层名称。第二部分不应一次性重命名或搬迁所有历史测试，只需要建立新的稳定 marker/命令和少量纵向入口。

## 4. 代表性纵向路径候选

首条纵向路径建议选择：

```text
受控课程/课节事实
  -> 公开 Tutor API
  -> Redis 队列
  -> Tutor worker
  -> 受控 provider stub
  -> Postgres 写入 TutorTurn / AgentRun / ProviderCall
  -> API 轮询读取最终结果
  -> 质量与成本读取 API 核对运行事实
```

选择 Tutor 作为第一条路径的原因：

- 是用户高频主流程；
- 同时经过 API、worker、Postgres、provider adapter 和第一部分观测事实；
- 不要求先完成资料上传、解析和课程生成的长前置流程；
- 能较早暴露队列、超时、repair、Provider Call 和迟到状态问题。

首条路径暂不强制浏览器自动化。Web 层在同一 Slice 中只建立一个最小浏览器 smoke Gate，避免把 CI、浏览器框架和五条链一次性交织。

## 5. CI 分层候选

| Gate | 默认触发 | 外部成本 | 环境 | 失败语义 |
|---|---|---:|---|---|
| Fast | 每个 PR | 0 | Python/Node | 必过 |
| Postgres | 每个 PR | 0 | 临时 Postgres | 必过，不允许 skip |
| Controlled System | 每个 PR 或合并前 | 0 | Compose + Redis + worker + stub | 必过 |
| Browser Smoke | 合并前 | 0 | Compose + Chromium | 必过或明确环境阻塞 |
| Compiler Matrix | 合并前 | 0 | 固定 Python/Java/C++ backend | 必过，不允许静默 skip |
| Real Provider Eval | 手动/定时 | 付费 | 显式 secrets | 不计入普通 PR 绿色状态 |
| Remote Tool Eval | 手动 | 可能付费 | Judge0/Wolfram 等 | 不计入普通 PR 绿色状态 |

## 6. 反事实要求

关键系统测试必须证明自己能够发现错误，而不是只检查“最终成功”：

- provider stub 返回 timeout，运行必须进入稳定 timeout 分类；
- repair 调用必须生成 `phase=repair`，移除 repair 时测试失败；
- worker 不消费队列时，测试必须以稳定的环境/超时诊断失败；
- 跨 workspace owner 绑定必须失败或安全降级；
- Provider Call recorder 被绕过时，纵向断言必须失败；
- Postgres 不可用时 Controlled System Gate 必须失败，而不是 skip；
- compiler/runtime 缺失时 Compiler Matrix 必须失败并指出缺少哪种语言。

## 7. 成本与数据边界

- 普通 PR 不调用真实付费 provider；
- provider stub 只返回固定结构、usage 和可控错误，不复制业务判定逻辑；
- 测试不得保存完整 prompt、回答、用户答案、Memory、provider key 或内部 URL；
- 系统测试使用隔离 workspace 和可清理测试数据；
- Postgres 仍是权威事实，不能以进程内列表代替最终断言；
- CI 日志只输出稳定 ID、状态、错误码和脱敏计数。

## 8. 本轮不处理

- 生产备份恢复；
- Qdrant rebuild runbook；
- storage reconciliation；
- Redis/Qdrant 认证；
- 非 root、HTTPS、反向代理和生产端口加固；
- 普通 PR 的真实 provider/Judge0/Wolfram 调用；
- Tutor、Practice、编程质量修复本身；
- 全量重写或迁移历史测试。

## 9. 待人工确认

1. 是否接受 Tutor 作为第一条真实纵向系统路径？
2. 是否接受普通 PR 的所有必过 Gate 均为零付费调用？
3. 是否接受 Postgres 与 Controlled System Gate 中环境缺失直接失败，不允许 skip？
4. 是否接受第二部分只拆为 Slice 2A 和 Slice 2B？
