# Spec 006：受控纵向系统测试与 CI Gate

状态：已于 2026-07-28 通过人工 Gate

日期：2026-07-28

## 1. 评审结论摘要

本 Slice 建立 Stage 5 第二部分的测试基础：用零付费、可重复的受控环境验证真实 API、Redis worker、Postgres 和 provider adapter 能共同完成用户主流程。

首条完整纵向路径选择 Tutor。Course generation、Practice generation、Practice grading 和 RAG Answer 在同一 Slice 补齐完整业务 orchestration 的 Provider Call 断言，但不要求首轮全部跨浏览器。

Postgres、Redis、worker 或受控 adapter 缺失时，受控系统 Gate 必须失败，不能静默 skip 或冒充通过。

## 2. 背景

当前仓库已有大量 unit、API、worker、Postgres 和 eval 测试，但没有仓库级 CI workflow，也没有真实 RQ worker 进程参与的自动化纵向路径。多数业务测试直接调用 helper/service，并 monkeypatch 队列或 provider；Postgres 不可达时部分关键测试会 skip；Web 只有 lint/build；五条 Provider Call 链尚未由完整业务 orchestration 共同证明。

本 Slice 的目标不是增加更多局部测试，而是建立少量高价值的真实纵向 Gate。

## 3. 目标

维护者可以在本地或 CI 中运行稳定命令，确认：

1. Tutor 请求经过公开 API 创建；
2. Redis 中的任务由真实 worker 消费；
3. provider 与 embedding 调用经过真实 HTTP adapter 边界，但由受控 stub 响应；
4. Tutor 结果、AgentRun 和 ProviderCall 写入 Postgres；
5. API 能读回最终结果和安全观测事实；
6. timeout、repair、workspace 隔离等关键破坏行为会使测试失败。

普通 PR 必须保持零付费，并明确区分快速、Postgres、受控系统、浏览器、编译器和远程 Gate。

## 4. 范围

### 4.1 Tutor 首条纵向路径

```text
测试准备的 workspace/course/lesson
  -> Tutor HTTP API
  -> Redis queue
  -> 真实 Tutor worker 进程
  -> 受控 model-services stub
  -> Qdrant 检索与 Postgres back-read
  -> Postgres
  -> Tutor HTTP read API
  -> AgentRun / ProviderCall read API
```

允许通过 fixture 直接准备课程和课节的权威数据库事实，以免把资料上传、解析和课程生成前置链混入首条路径。Tutor 请求本身必须通过公开 HTTP API 发起，worker 不得由测试函数直接调用。

### 4.2 五条 orchestration Provider Call 合同

以下链必须从公开业务 service 或完整 orchestration 入口进入：

- Course generation；
- Tutor；
- Practice generation；
- Practice grading；
- RAG Answer。

最终必须从 Postgres 查询 ProviderCall 并验证：

- workspace 与 owner；
- 正常阶段与 repair 阶段；
- Run 内 ordinal 单调且无重复；
- usage；
- provider 实际调用次数；
- timeout 映射为 `timed_out/provider_timeout`；
- 稳定失败码；
- 不记录 prompt、回答、用户答案、key、内部 URL 或绝对路径。

不得直接调用 recorder 或只检查 mock 调用参数作为最终证据。

### 4.3 CI 分层

| Gate | 普通 PR | 真实付费调用 | 结果要求 |
|---|---|---:|---|
| Fast | 是 | 否 | 必过 |
| Postgres | 是 | 否 | 必过，不允许 skip |
| Controlled System | 是 | 否 | 必过 |
| Web lint/build | 是 | 否 | 必过 |
| Browser Smoke | 合并前或普通 PR | 否 | 必过或明确环境失败 |
| Compiler Matrix | 合并前或普通 PR | 否 | Python/Java/C++ 不允许静默 skip |
| Real Provider Eval | 否，手动/定时 | 是 | 与普通 PR状态分离 |
| Remote Tool Eval | 否，手动 | 可能 | 与普通 PR 状态分离 |

Browser Gate 在首轮配置 Chromium-only Playwright，并在本地/CI 环境真实跑通后成为普通 PR 必过项。Compiler Matrix 仍先做环境预检；不得把尚未验证的编译环境标成已通过。

### 4.4 最小浏览器 smoke

- Web 首页可访问；
- 选择系统测试 workspace；
- 进入 Tutor；
- 发起固定但非领域硬编码的问题；
- 等待稳定终态；
- 页面显示回答或稳定失败状态；
- 运行记录可看到对应 Tutor Run。

浏览器测试只验证交互和投影，不判断 Tutor 内容质量。内容质量属于 Slice 2B。

首轮浏览器范围固定为 Chromium、单 worker 和一条 Tutor smoke。Firefox、WebKit、视觉快照及多设备矩阵不在本 Slice。

## 5. 受控 model-services stub

stub 是独立测试服务，不得在产品代码中增加测试模式或固定回答分支。它同时提供生成与 embedding 的现有 HTTP 协议入口，确保 Tutor 检索路径不会被 monkeypatch 绕过。

至少支持：

- `success`：固定合法响应和 usage；
- `repair`：首次结构无效，第二次合法；
- `timeout`：稳定触发 timeout；
- `failure`：稳定的 HTTP/连接失败；
- 调用计数和按顺序返回。
- 固定维度的 DashScope-compatible embedding 响应。

stub 日志只能记录场景 ID、调用序号、endpoint 类型、时间戳和可选 body 字节数，不得记录完整 prompt 或 Authorization。

## 6. 环境与数据生命周期

允许新增 test-only Compose override/profile，包含：

- Postgres；
- Redis；
- Qdrant；
- API；
- Tutor worker；
- model-services stub；
- system-test runner；
- Web 和浏览器 runner（若进入首轮）。

Qdrant 只有在首条 Tutor fixture 确实经过检索时才加入。若使用预置权威证据或受控 retrieval 边界，必须如实说明。

每次运行必须：

- 使用唯一 project/database/workspace 前缀；
- 不连接开发数据库；
- 清理容器、网络和测试卷；
- 报告清理失败的资源名称；
- 等待 Postgres、Redis、API、worker queue 和 stub readiness；
- 不以固定 sleep 作为唯一 readiness 判断。

## 7. 状态与失败语义

| 情况 | Gate 结果 |
|---|---|
| 断言失败 | failed |
| 必需服务无法启动 | environment_failed |
| 必需依赖缺失 | environment_failed |
| Postgres 测试全部 skip | failed |
| 编译器关键语言缺失 | environment_failed |
| 真实 provider 未配置 | remote_not_run，不影响普通 PR |
| 用户显式取消 | canceled |
| 超过系统测试总时限 | timed_out |

CI 可以使用平台原生 conclusion，但测试摘要必须保留稳定分类。

## 8. 反事实验收

至少覆盖：

1. 合法 stub 响应时 Tutor 纵向路径成功；
2. worker 不消费或错误 queue 时，以 worker/queue 诊断失败；
3. provider timeout 时，Tutor Run 和 ProviderCall 得到稳定 timeout 事实；
4. repair 场景产生正常阶段和 `repair` 阶段；
5. 绕过 ProviderCall recorder 时，数据库断言失败；
6. owner 或 workspace 绑定错误时，数据库/读取断言失败；
7. Postgres 或 Redis 缺失时 Gate 失败而非 skip；
8. 系统测试输出不含敏感字段。

反事实可由 stub 场景、错误环境配置或测试级替换构造，但最终断言必须读取公开结果或数据库事实。

## 9. 安全边界

- 普通 PR 不读取真实 provider secrets；
- workflow 不向 fork PR 暴露 secrets；
- stub 不接受或持久化真实 key；
- 日志不包含完整 prompt、回答、用户答案或检索正文；
- artifact 只保留 JUnit/JSON 摘要、稳定 ID、状态、计数和脱敏诊断；
- test-only 服务不得改变生产 Compose 的默认端口与网络声明。

## 10. 非目标

- Tutor、Practice 或课程生成质量优化；
- 固定质量阈值和真实 provider 基线；
- 全量浏览器覆盖；
- 资料上传与解析的首条纵向路径；
- 生产备份恢复与部署安全加固；
- 真实 Judge0/Wolfram 作为普通 PR Gate；
- 重写所有历史测试；
- 新增产品内测试专用 API 或业务分支。

## 11. 验收

### 自动化

- CI 配置语法有效；
- Fast 和 Web Gate 可独立运行；
- Postgres Gate 在受控 Postgres 中真实执行且关键文件零 skip；
- Tutor 纵向路径重复运行至少两次成功；
- 五条 orchestration Provider Call 合同测试通过；
- timeout、repair、worker 缺失等反事实通过；
- `docker compose config` 和 test profile build 通过；
- `git diff --check` 通过。

### 人工

- 查看一次 CI 分层结果，确认未运行的远程 Gate 没有显示为通过；
- 查看失败摘要，确认不暴露敏感正文；
- Chromium 浏览器 smoke 在本地和 CI 各完成一次。

## 12. 待人工 Gate

1. 接受 Tutor 作为首条跨 API、Redis worker、Postgres、Qdrant 和 model-services stub 的纵向路径。
2. 接受测试直接准备课程/课节数据库事实，但 Tutor 请求必须从公开 HTTP API 发起。
3. 接受 provider stub 为独立 test-only 服务，禁止产品代码出现固定回答分支。
4. 接受五条链都在 Slice 2A 补完整 orchestration Provider Call 断言，但只有 Tutor 首轮强制跨真实队列进程。
5. 接受普通 PR 零付费，真实 provider/Judge0/Wolfram Gate 手动或定时运行。
6. 接受 Postgres、Redis、worker 或关键编译器缺失时受控 Gate 失败，不允许静默 skip。
7. 接受首轮配置 Chromium-only Playwright 并在跑通后纳入普通 PR；Compiler Matrix 仍先做环境预检。
