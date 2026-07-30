# Stage 5 Part 2 Slice 2A 环境与实现路径预检

状态：Codex 事实盘点完成，供 Spec Gate 与 GLM 任务包使用

日期：2026-07-28

## 1. 结论摘要

Slice 2A 可实施，但不能把任务笼统交给实现者。当前代码事实要求：

1. Tutor 纵向路径必须包含 Qdrant 和受控 embedding 响应，不能只提供 chat provider stub；
2. Tutor API、Redis queue 和 RQ worker 的真实入口已经存在，可直接复用；
3. 当前 MCP execution 的 test fake 是字符串模拟器，不是真正的 Python/Java/C++ 编译环境；
4. Web 没有浏览器测试依赖，首轮不能在未验证前宣称 Browser Gate 已建立；
5. 仓库没有 `.github/workflows`，需要新建最小 CI，而不是改造既有 workflow；
6. 五条 Provider Call 链的完整 orchestration 测试可以复用第一部分 recorder，但必须重新从上层入口组织。

因此建议 Slice 2A 第一轮把 **Fast、Web、Postgres、Controlled Tutor System** 设为明确交付；Browser 和真实 Compiler Matrix 先建立 preflight 命令与失败报告，只有环境真实跑通后才升级为 PR 必过。

## 1.1 实现责任

人工于 2026-07-28 明确调整协作分工：

- Codex 负责 CI、Compose、model-services stub、Qdrant fixture、真实 worker、Playwright、readiness、清理和 Tutor 纵向样板；
- GLM 不修改上述外部交互基础设施；
- Codex 跑通 Tutor 样板后，GLM 仅可在既定 harness 中补其余四条 orchestration Provider Call 断言；
- Codex 负责最终独立验收和 OCR Gate。

## 2. Tutor 真实入口

### HTTP

- 创建 Session：
  - `POST /api/v1/workspaces/{workspace_id}/courses/{course_id}/tutor-sessions`
- 创建 Turn：
  - `POST /api/v1/workspaces/{workspace_id}/tutor-sessions/{session_id}/turns`
  - 必须提供 `Idempotency-Key`
- 读取 Turn：
  - `GET /api/v1/workspaces/{workspace_id}/tutor-turns/{turn_id}`
- SSE：
  - `GET /api/v1/workspaces/{workspace_id}/tutor-turns/{turn_id}/events`

首条系统测试使用创建和轮询读取即可；SSE 可保留给 Browser Gate，不必同时承担首个 runner 的稳定性风险。

### Queue

- queue：`learn-platform-tutor`
- enqueue：`learn_platform_api.services.queue.enqueue_tutor_turn`
- RQ target：`learn_platform_api.tutor_workers.run_tutor_turn`
- Compose `worker` 已订阅该 queue。

系统测试不得直接调用 `run_tutor_turn()`。

## 3. Tutor 所需真实依赖

Tutor worker 并非只调用生成模型。其搜索步骤经过：

```text
tutor_generation._search()
  -> retrieval.retrieve()
  -> workers.embed_texts()
  -> DashScope-compatible embedding HTTP
  -> Qdrant query
  -> Postgres back-read
```

因此受控环境至少需要：

- Postgres；
- Redis；
- Qdrant；
- API；
- Tutor worker；
- model-services stub；
- system-test runner。

### model-services stub

建议一个 test-only 服务同时暴露两个协议入口：

1. DeepSeek/OpenAI-compatible：
   - `POST /chat/completions`
2. DashScope-compatible embedding：
   - `POST /embeddings` 或由测试配置指向的等价路径；
   - 返回 `output.embeddings[].embedding`；
   - 维度必须等于测试配置的固定小维度。

名称应使用 `model-services-stub`，避免误导为只处理生成模型。

产品仍通过现有配置连接：

- `PRODUCT_GENERATION_BASE_URL`
- `PRODUCT_GENERATION_API_KEY`，使用明显的测试占位值；
- `PRODUCT_EMBEDDING_BASE_URL`
- `PRODUCT_EMBEDDING_API_KEY`，使用明显的测试占位值；
- `PRODUCT_EMBEDDING_DIMENSION`

不得修改产品代码绕过 provider/embedding 配置检查。

## 4. Fixture 最小事实

Tutor lesson scope 需要一致的：

- active Workspace；
- active Course；
- active CourseVersion；
- CourseSection；
- Lesson；
- published LessonVersion；
- CourseVersionSource；
- active SourceDocument；
- ready DocumentVersion；
- DocumentChunk；
- LessonCitation；
- Qdrant collection 和对应 chunk point；
- TutorSession。

推荐由 system-test runner 使用产品 ORM/fixture builder 写入 Postgres，并通过 Qdrant 客户端写入与固定 embedding 维度一致的 point。不得通过产品新增 test-only API。

测试问题应与 fixture 文本存在通用词法支持，避免 relevance gate 依赖偶然向量分数；不能针对生产逻辑增加关键词分支。

## 5. 生成 stub 的响应序列

Tutor 当前可能先 plan/search，再 answer，并可能 repair。stub 需要按场景和调用序号返回符合现有 JSON 合同的内容。

最低场景：

- success：合法 plan + 合法 answer；
- repair：合法 plan + 非法 answer + 合法 repair；
- timeout：在指定调用序号阻塞超过测试 timeout；
- failure：指定调用序号返回稳定 HTTP 错误。

场景选择使用 test-only header 或 base URL 路径/独立容器环境变量。优先使用每次测试独立 stub 实例或独立 scenario ID，避免并发测试共享可变全局序号。

## 6. CI 与 Compose 事实

### 当前存在

- API Dockerfile `test` target；
- Compose 中的 Postgres、Redis、Qdrant、API、Web、worker；
- Docker healthcheck；
- `api-test` profile。

### 当前缺失

- `.github/workflows`；
- model-services stub；
- system-test runner；
- test-only Compose override；
- worker queue readiness；
- JUnit/JSON 分层摘要；
- 清理脚本；
-浏览器 runner。

### 建议文件边界

候选新增：

- `.github/workflows/ci.yml`
- `compose.system-test.yml`
- `tests/system/` 或 `apps/api/tests/system/`
- `tests/system/model_services_stub/`
- `scripts/system-test.ps1`
- `scripts/system-test.sh`

最终路径须遵循仓库现有命名，GLM 不得自行把测试服务放入产品 package。

## 7. Browser 预检结论

`apps/web/package.json` 当前没有 Playwright、Vitest 或 Jest。现阶段：

- lint/build 可以立即进入 PR Gate；
- 自动 Browser Gate 尚不具备依赖基础；
- 人工浏览器 smoke 已有经验，可作为 Slice 2A 首轮人工 Gate；
- 若决定引入 Playwright，属于明确的新 dev dependency，必须在任务包中单独批准并锁定最小用例。

人工 Gate 已于 2026-07-28 接受在 Slice 2A 配置最小 Playwright。任务包允许：

- 在 `apps/web` 增加 `@playwright/test` dev dependency；
- 只安装 Chromium；
- 新增 `playwright.config.ts` 和一个 Tutor smoke spec；
- CI 使用单 worker；
- 失败时保留 trace、截图和 JUnit/HTML 报告；
- 浏览器测试只连接 test-only Compose，不启动第二套产品逻辑。

首轮不启用 Firefox/WebKit、多浏览器矩阵、视觉快照或大规模页面覆盖。

## 8. Compiler 预检结论

当前：

- API 与 MCP execution 镜像基于 `python:3.12-slim`；
- 没有安装 JDK 或 C++ toolchain；
- MCP adapter 的 fake backend 使用 `_simulate_python/_simulate_java/_simulate_cpp`；
- fake backend 只能验证协议映射和状态归一化，不能证明真实编译执行。

因此不能把现有 fake backend 计为 Compiler Matrix 通过。

建议：

- Slice 2A 首轮增加 `compiler_preflight`，明确报告 Python/Java/C++ backend 为 `environment_failed` 或 `not_configured`；
- 不在第一实现包内自行设计新的 sandbox；
- 真正固定三语言 backend 需要后续独立人工 Gate，仍属于 Slice 2A，而不是新产品 Slice。

## 9. GLM 执行顺序

保持一个 Slice，但任务包内部必须按顺序：

### Phase A：CI 命令与报告骨架

- Fast/Web/Postgres 命令；
- 关键 Postgres 测试零 skip 检查；
- workflow 骨架；
- 不接系统业务。

### Phase B：受控模型服务与 Compose

- model-services stub；
- Postgres/Redis/Qdrant/API/worker/stub/runner profile；
- readiness 和清理；
- 只验证服务连通。

### Phase C：Tutor 纵向路径

- fixture；
- HTTP 创建；
-真实 worker；
-最终数据库和读取 API 断言；
- success/repair/timeout 反事实。

### Phase D：其余四条 orchestration

- Course generation；
- Practice generation；
- Practice grading；
- RAG Answer；
- 最终 ProviderCall 数据库断言。

### Phase E：Browser Gate 与 Compiler 决策点

- 配置 Chromium-only Playwright；
- 增加一条 Tutor 浏览器 smoke；
- Compiler 只提交 preflight 结果；
- 未经新的人工确认不安装 JDK/GCC、不新增编译 sandbox。

每个 Phase 失败时停止，不通过同步调用 worker、绕过 retrieval 或修改产品合同让测试变绿。

## 10. 需要反映进任务包的停点

GLM 必须停止并报告：

- Tutor 真实入口要求修改公开 API；
- stub 无法通过现有 provider/embedding 配置接入；
- fixture 必须修改产品 schema；
- worker 只能通过直接函数调用才能完成；
- Compose 会连接开发数据库或复用开发 volume；
- 关键测试只能靠源码字符串检查；
- 需要扩展到 Firefox/WebKit、视觉回归、JDK/GCC 或新增执行 sandbox；
- 连续两个 Phase 修正后仍无法稳定复跑。
