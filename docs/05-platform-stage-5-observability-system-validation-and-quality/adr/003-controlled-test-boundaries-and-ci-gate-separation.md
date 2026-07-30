# ADR 003：受控测试边界与 CI Gate 分离

状态：已于 2026-07-28 通过人工 Gate

日期：2026-07-28

## 1. 决策摘要

Stage 5 第二部分采用三项边界：

1. model-services stub 是独立 test-only 进程，提供生成与 embedding 协议，产品代码不增加测试模式；
2. 纵向系统测试使用真实 API、Redis worker 和 Postgres，最终以公开读取和数据库事实断言；
3. 零付费 PR Gate 与真实 provider/远程工具 Gate 完全分离，未运行不能显示为通过。

## 2. 背景

局部测试 monkeypatch provider、队列或 worker，适合 focused regression，但不能证明真实进程边界。把真实 provider 放入普通 PR 又会引入不稳定、成本、secret 暴露和 fork PR 无法运行等问题。

因此需要一个经过真实产品边界、但不依赖付费服务的受控系统层。

## 3. 决策

### 3.1 独立 model-services stub

受控 stub 通过网络提供与现有 generation 和 embedding adapter 兼容的最小响应。产品通过正常配置指向 stub，测试不得 monkeypatch 产品 orchestration，也不得加入 `if testing` 固定回答分支。

stub：

- 不打包进生产镜像；
- 不进入默认生产 Compose；
- 不读取真实 secrets；
- 不记录 prompt 正文；
- 只支持 Spec 锁定的少量场景。

### 3.2 真实队列和数据库

Tutor 首条纵向路径必须使用公开 HTTP API、Redis、独立 RQ worker 进程和 Postgres。不得使用进程内 fake queue 代替系统 Gate；focused tests 仍可继续使用 monkeypatch。

### 3.3 Gate 分离

CI 分为零付费自动 Gate、受控环境 Gate，以及手动或定时远程 Gate。真实 provider、Judge0 和 Wolfram 不属于普通 PR 必过 Gate；未触发时记录 `remote_not_run`，不记录 passed。

### 3.4 环境缺失不是 skip

开发者单独运行 focused tests 时，部分环境测试可以 skip；在声明为 Postgres、Controlled System 或 Compiler Gate 的命令中，关键依赖缺失必须使 Gate 失败。

## 4. 影响

### 正面

- 普通 PR 可重复且零付费；
- 系统测试真实跨越 API、队列、worker 和数据库；
- provider 故障可以稳定脚本化；
- 远程服务不稳定不会污染普通 PR；
- 绕过 recorder 或错误 owner 会被数据库事实发现。

### 代价

- 需要维护 stub 与 adapter 合同；
- Compose 系统测试更慢；
- 需要可靠的清理和 readiness；
- stub 不能证明真实模型内容质量；
- real-provider eval 仍需 Slice 2B 单独维护。

## 5. 未采用方案

- 全部系统测试 monkeypatch provider：不能证明网络 adapter 和进程边界。
- 普通 PR 调用真实 provider：成本、稳定性和 secrets 风险不可接受。
- 产品代码加入测试模式固定回答：污染产品合同并形成测试捷径。
- 第一轮让五条链全部跨真实 worker：范围过大，先用 Tutor 建立样板。
- SQLite 代替系统测试 Postgres：无法验证正式事实来源和约束。

## 6. 生效条件

本 ADR 只有在以下事项均经人工接受后生效：

- Spec 006；
- provider stub 独立进程边界；
- Tutor 真实队列路径；
- PR 与远程 Gate 分离；
- 关键环境缺失失败语义。
