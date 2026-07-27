# 数据库与部署计划

版本日期：2026-07-27

状态：当前架构指导文档

## 1. 当前事实

正确仓库已经建立 `apps/api`、`apps/web`、Postgres、Redis、Qdrant、Alembic、
worker/reconciler 和 Docker Compose 产品层。Platform Stage 4 已完成；课程、
Tutor、练习、掌握度、Memory、受控工具和异步任务均已有 Postgres 权威事实，
并保留 `agent_runs/agent_tool_calls` 最小审计记录。Stage 5 可观测、系统验证与
质量优化的顶层方向已经通过人工 Gate，尚未批准新增 eval/cost schema 或
migration。成本展示统一使用人民币，不建设多币种或实时汇率系统。

Framework/domain 仍可复用的既有存储能力：

- `hello_agents/storage/qdrant_store.py`：Qdrant vector store。
- `hello_agents/memory/storage/document_store.py`：包括 SQLiteDocumentStore 在内的 memory 存储抽象。
- `hello_agents/memory/storage/neo4j_store.py`：可选图存储能力。
- `academic_companion/memory_extensions`：UserModel 和 research notes 本地持久化。
- `memory/`、`memory_data/`：本地运行数据，已忽略，不是产品数据库。
- `data/`：内置测试与演示材料，不是用户上传目录。

根 `pyproject.toml` 继续面向 framework/domain；产品 API/Web 已分别拥有依赖和配置边界。凭据仍只由本地环境提供，不进入日志、公开 API 或提交。

## 2. 已确认原则

| 组件 | 角色 | 权威性 |
|---|---|---|
| Postgres | 产品业务数据库 | 权威事实来源 |
| Local/object storage | 原始文件和派生大文本 | 文件字节来源 |
| Qdrant | embedding 与检索 payload | 可重建派生索引 |
| Redis | 队列、锁、缓存、限流 | 非权威 |
| SQLite | framework demo、快速测试或未来 local-only 模式 | 非正式 self-host 主路径 |
| Neo4j | 未来可选概念图 adapter | 非默认依赖 |

第一产品形态是 self-host。用户通过 Docker Compose 启动服务，并自行提供 LLM/embedding 凭据。

## 3. 产品数据所有权

### 3.1 Postgres

Postgres 保存 workspace、资料生命周期、后台任务、课程、练习、产品 memory、trace、eval 和成本等业务事实。

Postgres 不保存大型原始文件 blob，除非后续 ADR 明确改变策略。

### 3.2 文件存储

第一版使用本地 volume，通过 storage adapter 访问：

```text
storage/
  workspaces/<workspace_id>/
    documents/<document_id>/
      versions/<version_id>/
        original.<ext>
        parsed/content.md
        parse-report.json
  exports/
```

数据库只保存相对 storage URI、hash、MIME type、大小和状态，不保存宿主机绝对路径。后续切换到 S3/MinIO/OSS 时替换 adapter，不改变核心业务关系。

### 3.3 Qdrant

Qdrant 只保存 vector 和检索所需的最小 payload，例如：

```json
{
  "workspace_id": "...",
  "document_id": "...",
  "document_version_id": "...",
  "chunk_id": "...",
  "heading_path": "...",
  "content_hash": "...",
  "chunk_type": "source|lesson|exercise|memory"
}
```

约束：

- 用户资料检索必须带 workspace filter。
- citation 正文和删除状态以 Postgres/storage 回读为准。
- collection 名称和向量维度是显式配置合同。
- 维度变化需要显式 rebuild，不静默创建不兼容索引。
- Qdrant 不保存唯一 chunk 正文或唯一删除状态。

是否使用单 collection 在 Stage 2 ADR 确认；Stage 1 不提前建立产品 collection。

### 3.4 Redis

Redis 传输 job，不拥有 job 事实。推荐语义：

1. API 先提交 Postgres 业务记录和 job。
2. 提交后 enqueue。
3. enqueue 失败时保留 job 并标记 `queue_failed`。
4. 显式 retry 重新 enqueue 同一业务 job。
5. worker 使用业务 job ID 保证幂等。

Stage 1 只启动 Redis 和 readiness；worker 在 Stage 2 引入。

## 4. 分阶段 Schema

### Stage 1：最小产品壳

只建立平台壳真正需要的表：

```text
workspaces
```

如最小 capability adapter 需要记录执行，可增加受限的 `agent_runs`，但必须由 Stage 1 spec 证明必要性。不要为了“以后可能用到”一次建立全部 schema。

### Stage 2：资料生命周期

```text
source_documents
document_versions
document_parse_reports
document_chunks
ingestion_jobs
ingestion_batches
ingestion_batch_items
rag_query_traces
rag_answer_traces
```

document 属于 workspace，version 不覆盖历史版本，chunk 属于明确 version，job 有稳定业务 ID、状态、尝试次数和错误码。batch/item 只汇总一次批量操作，不取代逐文件 document/version/job；answer trace 保存生成配置、引用、用量和状态，默认不保存完整问题、prompt 或回答历史正文。

### Stage 3：章节学习

```text
courses
course_sections
lessons
lesson_versions
lesson_citations
```

Stage 3 一旦引入真正的 Tutor 或生成 Agent，必须同时保留最小可审计的
run/tool 记录。当前已经采用受限的 `agent_runs/agent_tool_calls`。Stage 5 的
目标是统一质量与成本治理、系统验证和基于证据的优化，不是等到 Stage 5 才
第一次记录 Agent 运行事实。

### Stage 4：练习与记忆

```text
concepts
concept_edges
exercises
exercise_attempts
learning_events
concept_mastery
review_items
memories
```

### Stage 5：可观测与成本候选数据

```text
agent_runs（已有）
agent_tool_calls（已有）
eval_cases
eval_results
cost_events
```

`eval_cases`、`eval_results` 和 `cost_events` 仍是候选；是否建表、复用离线
fixture，或采用聚合投影，必须先完成 Stage 5 事实盘点并由对应 Spec/ADR 决定。
不得为了 dashboard 预先创建 schema。

## 5. Existing assets 的处理

### `academic_companion` memory

当前 UserModel、research notes 和本地 memory 保留为 prototype 能力。Stage 1 不迁移其数据。产品 memory schema 在 Stage 4 设计，并明确兼容或导入策略。

### 八股与 LeetCode

它们是 fixture/eval 材料，不要求导入 product Postgres，不建立专用 workspace 或删除模型。可以抽取少量样本验证 Stage 2/3/4 合同。

### 现有 Qdrant 数据

现有 `cs_fundamentals`、`leetcode`、research notes 等 collection 属于 prototype/runtime 数据。新 product collection 不复用其事实语义，除非 Stage 2 ADR 明确兼容方案。

## 6. 配置边界

根 `.env.example` 继续描述 `hello_agents` 和 `academic_companion` demo 所需的 LLM、embedding、Qdrant、Neo4j 等变量。

Stage 1 应建立独立 product settings，至少覆盖：

```text
APP_NAME
ENVIRONMENT
DATABASE_URL
QDRANT_URL
QDRANT_API_KEY
REDIS_URL
STORAGE_ROOT
CORS_ORIGINS
```

Stage 2 的 product embedding、collection 和 queue 配置使用明确命名空间，避免和 framework demo 的 `EMBED_*`、`QDRANT_COLLECTION` 串扰。具体前缀由 Stage 2 ADR 确认。

敏感配置不得通过 system info、readiness 或普通日志返回。

## 7. Docker Compose 目标

Stage 1 包含：

```text
postgres
qdrant
redis
api
web
```

Stage 2 增加 `worker`。Stage 1 不加入 Neo4j、MinIO、反向代理或 HTTPS。

## 8. Migration 与启动

- 使用 Alembic 管理 product Postgres schema。
- migration 与 app 依赖位于 product API 边界，不进入 `hello_agents` package。
- Stage 1 单机 Compose 可以由 API 容器在启动前执行 migration。
- Stage 2 worker 必须等待 migration owner 完成，不并发执行 migration。
- 后续生产化再评估独立 one-shot migration service。

每个 schema 变更必须有对应 Stage spec/ADR、已有数据考虑和 migration test，不能只依赖 ORM 自动建表。

## 9. 删除与重建

用户资料删除的权威顺序：

1. Postgres 标记删除或进入删除状态。
2. 默认查询立即排除该资料。
3. cleanup job 删除 Qdrant points。
4. 根据保留策略删除 storage 文件。
5. cleanup 失败不回滚权威删除状态，可重试和 reconciliation。

索引重建从 Postgres 读取有效 version/chunk，从 storage 读取正文，重新计算 embedding，并使用稳定 chunk ID upsert Qdrant。

## 10. Self-host 安全基线

- `.env` 和 provider key 不提交 Git。
- readiness 只返回组件是否可用，不返回内部 URL、绝对路径或凭据。
- API 日志不记录上传全文、完整 prompt、API key 或 provider 原始错误正文。
- 用户资源即使第一版单用户，也保留 workspace 外键和 filter 纪律。
- 默认端口暴露、Redis/Qdrant auth、容器非 root 和 HTTPS 顺延到后续部署加固
  阶段；现有文档必须继续明确本地开发边界，不能把暂缓写成已经安全。

## 11. 备份与恢复目标

权威备份至少包含 Postgres dump、storage volume 和非敏感配置模板。Qdrant 和
Redis 不作为唯一恢复来源。备份恢复、索引重建 runbook 和 storage
reconciliation 顺延到后续部署加固阶段。

## 12. 实施顺序

1. Stage 0R 完成依赖/测试基线和 prototype contract inventory。
2. Stage 1 spec/ADR 决定 product app、依赖和误仓库参考实现采用方式。
3. 建立 workspace migration、API/Web 和 Compose。
4. Stage 2 再建立 document/job/storage/Qdrant 合同和 worker。
5. 后续增加 course、exercise、memory、eval 和 hardening。

相关文档：

- [学习平台蓝图](./LEARNING_AGENT_BLUEPRINT.md)
- [开发路线](./SELF_HOST_DEVELOPMENT_ROADMAP.md)
- [产品分层 ADR](./00R-platform-baseline-reconstruction/adr/001-product-layer-and-dependency-boundaries.md)
