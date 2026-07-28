import { Activity, ChevronDown, ChevronRight, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  AgentRunDetail,
  AgentRunQuery,
  AgentRunRole,
  AgentRunSummary,
  QualityCostBusinessType,
  QualityCostQuery,
  QualityCostSummary,
  QualityCostWindow,
  QualityCostStatus,
  fetchAgentRun,
  fetchAgentRuns,
  fetchProviderCalls,
  fetchQualityCostSummary,
  ProviderCallRead,
} from "../lib/api";

type LoadState = "loading" | "ready" | "error";

const WINDOW_LABEL: Record<QualityCostWindow, string> = {
  "24h": "24 小时",
  "7d": "7 天",
  "30d": "30 天",
};

const STATUS_LABEL: Record<string, string> = {
  started: "进行中",
  succeeded: "成功",
  failed: "失败",
  canceled: "已取消",
};

const ROLE_LABEL: Record<string, string> = {
  course_architect: "课程架构",
  lesson_writer: "课节撰写",
  tutor: "辅导",
  exercise_author: "练习生成",
  answer_grader: "练习评分",
  scientific_solution_grader: "科学题验证",
  code_execution: "代码执行",
};

const IDENTITY_KIND_LABEL: Record<string, string> = {
  course_generation: "课程生成",
  tutor: "辅导",
  practice: "练习",
  code_execution: "代码执行",
  unknown: "其他运行",
};

const UNKNOWN_REASON_LABEL: Record<string, string> = {
  provider_missing: "Provider 缺失",
  model_missing: "模型缺失",
  usage_missing: "用量缺失",
  rate_missing: "价格缺失",
};

const ERROR_CODE_LABEL: Record<string, string> = {
  generation_canceled: "运行已取消",
  generation_internal_error: "内部错误",
  generation_provider_unavailable: "模型服务暂不可用",
  generation_provider_unconfigured: "模型服务未配置",
  generation_budget_exceeded: "超出运行预算",
  invalid_agent_artifact: "生成结果不符合规范",
  insufficient_evidence: "资料证据不足",
  unknown_citation: "引用校验失败",
  source_snapshot_stale: "课程来源已变化",
  queue_unavailable: "任务队列暂不可用",
  queue_failed: "任务队列失败",
};

const SUMMARY_LOAD_ERROR = "摘要读取失败，请稍后重试";
const RUNS_LOAD_ERROR = "异常运行读取失败，请稍后重试";

const safeErrorLabel = (code: string): string => ERROR_CODE_LABEL[code] ?? "运行出现问题";
const safeUnknownReason = (reason: string): string => UNKNOWN_REASON_LABEL[reason] ?? reason;
const safeIdentityLabel = (run: AgentRunSummary): string => {
  if (run.identity.course_deleted) return "已删除对象";
  const kind = run.identity.kind;
  const kindLabel = IDENTITY_KIND_LABEL[kind] ?? "其他运行";
  const parts = [kindLabel];
  if (run.identity.course_title) parts.push(run.identity.course_title);
  if (run.identity.lesson_title) parts.push(run.identity.lesson_title);
  return parts.join(" · ");
};
const safeRoleLabel = (role: string): string => ROLE_LABEL[role] ?? "其他运行";

function formatCNY(amount: string): string {
  return `¥${amount}`;
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "暂无样本";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}/K`;
  return String(n);
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
}

const isKnownRole = (role: string): role is AgentRunRole =>
  Object.prototype.hasOwnProperty.call(ROLE_LABEL, role);

// ---------------------------------------------------------------------------
// Pure helpers — extracted for testability (smoke fix §6)
// ---------------------------------------------------------------------------

/** Filter runs by summary window bounds (from/to). */
export function filterRunsByWindow(
  runs: AgentRunSummary[],
  bounds: { from: string; to: string } | null,
): AgentRunSummary[] {
  if (!bounds) return runs;
  const fromMs = new Date(bounds.from).getTime();
  const toMs = new Date(bounds.to).getTime();
  return runs.filter((r) => {
    const t = new Date(r.created_at).getTime();
    return t >= fromMs && t <= toMs;
  });
}

/** Filter runs by business type using safe identity.kind. */
export function filterRunsByBusinessType(
  runs: AgentRunSummary[],
  businessType: string,
): AgentRunSummary[] {
  if (!businessType) return runs;
  return runs.filter((r) => r.identity.kind === businessType);
}

/** Sort by created_at descending and truncate to limit. */
export function sortAndTruncateRuns(
  runs: AgentRunSummary[],
  limit: number,
): AgentRunSummary[] {
  return runs
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, limit);
}

/** Fix 6: Safe cost display — only format CNY when status is calculated and amount is non-null. */
export function safeCostDisplay(
  cost: { status: string; amount: string | null | undefined },
): string {
  if (cost.status === "calculated" && cost.amount != null) {
    return formatCNY(cost.amount);
  }
  return "成本未知";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function QualityCostPanel({ workspaceId }: { workspaceId: string }) {
  const [windowValue, setWindowValue] = useState<QualityCostWindow>("24h");
  const [filterRole, setFilterRole] = useState("");
  const [filterStatus, setFilterStatus] = useState<QualityCostStatus | "">("");
  const [filterBusinessType, setFilterBusinessType] = useState("");

  const [summary, setSummary] = useState<QualityCostSummary | null>(null);
  const [summaryLoad, setSummaryLoad] = useState<LoadState>("loading");
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [failedRuns, setFailedRuns] = useState<AgentRunSummary[]>([]);
  const [failedRunsLoad, setFailedRunsLoad] = useState<LoadState>("loading");
  const [failedRunsError, setFailedRunsError] = useState<string | null>(null);

  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<AgentRunDetail | null>(null);
  const [runDetailError, setRunDetailError] = useState<string | null>(null);

  const [drillRunId, setDrillRunId] = useState<string | null>(null);
  const [providerCalls, setProviderCalls] = useState<ProviderCallRead[]>([]);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillError, setDrillError] = useState<string | null>(null);

  // Request sequence counters for coordinated refresh (Fix 3: single counter set)
  const refreshSeq = useRef(0);
  const failedSectionRef = useRef<HTMLDivElement>(null);

  // Fix 1: Independent request sequence for run detail
  const detailSeq = useRef(0);

  // Fix 2: Independent request sequence for provider call drill
  const drillSeq = useRef(0);

  // Smoke fix: stable ref for summary window bounds
  const summaryBoundsRef = useRef<{ from: string; to: string } | null>(null);

  const build1CQuery = useCallback((): QualityCostQuery => {
    const q: QualityCostQuery = { window: windowValue };
    if (isKnownRole(filterRole)) q.role = filterRole;
    if (filterStatus) q.status = filterStatus;
    if (filterBusinessType) q.business_type = filterBusinessType as QualityCostBusinessType;
    return q;
  }, [windowValue, filterRole, filterStatus, filterBusinessType]);

  const buildFailedRunsQuery = useCallback((): AgentRunQuery[] => {
    if (filterStatus === "started" || filterStatus === "succeeded") {
      return [];
    }
    const queries: AgentRunQuery[] = [];
    const baseRole = isKnownRole(filterRole) ? filterRole as AgentRunRole : undefined;
    if (!filterStatus || filterStatus === "failed") {
      queries.push({ status: "failed", limit: 20, role: baseRole });
    }
    if (!filterStatus || filterStatus === "canceled") {
      queries.push({ status: "canceled", limit: 20, role: baseRole });
    }
    return queries;
  }, [filterRole, filterStatus]);

  // --- Coordinated refresh (Fix 3): single entry point for all refreshes -------
  // Top refresh, summary retry, failed-runs retry all go through refreshAll.
  // One monotonic counter (refreshSeq) prevents cross-cancellation.

  const refreshAll = useCallback(async (signal?: AbortSignal) => {
    const seq = ++refreshSeq.current;

    // Phase 1: summary
    setSummaryLoad("loading");
    let freshBounds: { from: string; to: string } | null = summaryBoundsRef.current;
    try {
      const data = await fetchQualityCostSummary(workspaceId, build1CQuery(), signal);
      if (seq !== refreshSeq.current) return;
      setSummary(data);
      freshBounds = { from: data.from, to: data.to };
      summaryBoundsRef.current = freshBounds;
      setSummaryLoad("ready");
      setSummaryError(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (seq !== refreshSeq.current) return;
      setSummaryLoad("error");
      setSummaryError(SUMMARY_LOAD_ERROR);
    }

    // Phase 2: failed runs
    if (signal?.aborted) return;
    const queries = buildFailedRunsQuery();
    if (queries.length === 0) {
      setFailedRuns([]);
      setFailedRunsLoad("ready");
      setFailedRunsError(null);
      return;
    }
    setFailedRunsLoad("loading");
    setFailedRuns([]);
    try {
      const allRuns: AgentRunSummary[] = [];
      for (const q of queries) {
        const runs = await fetchAgentRuns(workspaceId, q, signal);
        if (seq !== refreshSeq.current) return;
        allRuns.push(...runs);
      }
      const windowFiltered = filterRunsByWindow(allRuns, freshBounds);
      const businessFiltered = filterRunsByBusinessType(windowFiltered, filterBusinessType);
      setFailedRuns(sortAndTruncateRuns(businessFiltered, 20));
      setFailedRunsLoad("ready");
      setFailedRunsError(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (seq !== refreshSeq.current) return;
      setFailedRunsLoad("error");
      setFailedRunsError(RUNS_LOAD_ERROR);
    }
  }, [workspaceId, build1CQuery, buildFailedRunsQuery, filterBusinessType]);

  // Effect: fire coordinated refresh when filters change
  useEffect(() => {
    const controller = new AbortController();
    void refreshAll(controller.signal);
    return () => controller.abort();
  }, [refreshAll]);

  // Effect: invalidate detail/drill requests when workspaceId changes or on unmount
  useEffect(() => {
    // On workspaceId change, bump both sequence counters and clear detail/drill state
    // so in-flight requests for the old workspace cannot overwrite state.
    detailSeq.current += 1;
    drillSeq.current += 1;
    setExpandedRunId(null);
    setRunDetail(null);
    setRunDetailError(null);
    setDrillRunId(null);
    setProviderCalls([]);
    setDrillLoading(false);
    setDrillError(null);
  }, [workspaceId]);

  // --- Fix 1: toggleRun with independent request sequence ----------------------
  // Monotonic detailSeq prevents late-arriving A from overwriting B's detail.
  // Collapsing a record invalidates in-flight detail requests.

  const toggleRun = useCallback(async (runId: string) => {
    if (expandedRunId === runId) {
      // Collapse: invalidate any in-flight detail AND drill requests
      detailSeq.current += 1;
      drillSeq.current += 1;
      setExpandedRunId(null);
      setRunDetail(null);
      setRunDetailError(null);
      setDrillRunId(null);
      setProviderCalls([]);
      setDrillLoading(false);
      setDrillError(null);
      return;
    }
    const seq = ++detailSeq.current;
    setExpandedRunId(runId);
    setRunDetail(null);
    setRunDetailError(null);
    setDrillRunId(null);
    try {
      const detail = await fetchAgentRun(workspaceId, runId);
      if (seq !== detailSeq.current) return;
      setRunDetail(detail);
    } catch {
      if (seq !== detailSeq.current) return;
      setRunDetailError("运行详情读取失败");
    }
  }, [workspaceId, expandedRunId]);

  // --- Fix 2: loadProviderCalls with independent request sequence --------------
  // Monotonic drillSeq prevents late-arriving A from overwriting B's calls.
  // Closing drill invalidates in-flight drill requests.

  const loadProviderCalls = useCallback(async (runId: string) => {
    if (drillRunId === runId) {
      // Close: invalidate any in-flight drill request
      drillSeq.current += 1;
      setDrillRunId(null);
      return;
    }
    const seq = ++drillSeq.current;
    setDrillRunId(runId);
    setDrillLoading(true);
    setDrillError(null);
    setProviderCalls([]);
    try {
      const calls = await fetchProviderCalls(workspaceId, runId);
      if (seq !== drillSeq.current) return;
      setProviderCalls(calls);
      setDrillLoading(false);
    } catch {
      if (seq !== drillSeq.current) return;
      setDrillError("模型调用读取失败");
      setDrillLoading(false);
    }
  }, [workspaceId, drillRunId]);

  const scrollToFailedRuns = useCallback(() => {
    failedSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    failedSectionRef.current?.focus({ preventScroll: true });
  }, []);

  const showSummarySpinner = summaryLoad === "loading" && summary === null;
  const showSummaryError = summaryLoad === "error";
  const showFailedSpinner = failedRunsLoad === "loading";
  const showFailedError = failedRunsLoad === "error";

  const hasCalculatedCost = summary && summary.cost.calculated_call_count > 0;
  const hasOnlyUnknown = summary && summary.cost.calculated_call_count === 0 &&
    (summary.cost.unknown_call_count > 0 || summary.cost.runs_without_provider_calls > 0);
  const hasNoCostData = summary && summary.cost.calculated_call_count === 0 &&
    summary.cost.unknown_call_count === 0 && summary.cost.runs_without_provider_calls === 0 &&
    summary.provider_calls.total === 0;

  const statusExcludesFailures = filterStatus === "started" || filterStatus === "succeeded";

  return (
    <section className="quality-cost-panel" aria-labelledby="quality-cost-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">质量与成本</span>
          <h2 id="quality-cost-title">质量与成本</h2>
        </div>
        <button
          aria-label="刷新质量与成本"
          className="icon-button"
          disabled={summaryLoad === "loading"}
          onClick={() => void refreshAll()}
          title="刷新质量与成本"
          type="button"
        >
          {summaryLoad === "loading" ? <LoaderCircle className="spin" /> : <RefreshCw />}
        </button>
      </div>

      <div className="runs-filters">
        <div className="segmented-control" role="radiogroup" aria-label="时间范围">
          {(["24h", "7d", "30d"] as QualityCostWindow[]).map((w) => (
            <button
              key={w}
              role="radio"
              aria-checked={windowValue === w}
              className={windowValue === w ? "active" : ""}
              onClick={() => setWindowValue(w)}
              type="button"
            >
              {WINDOW_LABEL[w]}
            </button>
          ))}
        </div>
        <label>
          业务类型
          <select aria-label="按业务类型筛选" onChange={(e) => setFilterBusinessType(e.target.value)} value={filterBusinessType}>
            <option value="">全部</option>
            <option value="course_generation">课程生成</option>
            <option value="tutor">辅导</option>
            <option value="practice">练习</option>
            <option value="code_execution">代码执行</option>
            <option value="unknown">其他</option>
          </select>
        </label>
        <label>
          角色
          <select aria-label="按角色筛选" onChange={(e) => setFilterRole(e.target.value)} value={filterRole}>
            <option value="">全部角色</option>
            <option value="course_architect">课程架构</option>
            <option value="lesson_writer">课节撰写</option>
            <option value="tutor">辅导</option>
            <option value="exercise_author">练习生成</option>
            <option value="answer_grader">练习评分</option>
            <option value="scientific_solution_grader">科学题验证</option>
            <option value="code_execution">代码执行</option>
          </select>
        </label>
        <label>
          状态
          <select aria-label="按状态筛选" onChange={(e) => setFilterStatus(e.target.value as QualityCostStatus | "")} value={filterStatus}>
            <option value="">全部状态</option>
            <option value="started">进行中</option>
            <option value="succeeded">成功</option>
            <option value="failed">失败</option>
            <option value="canceled">已取消</option>
          </select>
        </label>
      </div>

      {showSummaryError ? (
        <div className="notice error" role="alert">
          <TriangleAlert size={18} />
          <span>{summaryError ?? "摘要读取失败"}</span>
          {/* Fix 3: retry goes through unified refreshAll */}
          <button className="secondary-button" onClick={() => void refreshAll()} type="button">重试</button>
        </div>
      ) : null}

      {summary ? (
        <>
          <div className="metric-band" role="region" aria-label="运行健康">
            <div className="metric-item">
              <span className="metric-value">{summary.runs.total}</span>
              <span className="metric-label">总运行</span>
            </div>
            <div className="metric-item">
              <span className="metric-value status-succeeded">{summary.runs.by_status.succeeded}</span>
              <span className="metric-label">成功</span>
            </div>
            <div className="metric-item">
              <span className="metric-value status-failed">{summary.runs.by_status.failed}</span>
              <span className="metric-label">失败</span>
            </div>
            <div className="metric-item">
              <span className="metric-value status-canceled">{summary.runs.by_status.canceled}</span>
              <span className="metric-label">已取消</span>
            </div>
            <div className="metric-item">
              <span className="metric-value status-started">{summary.runs.by_status.started}</span>
              <span className="metric-label">进行中</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{formatDuration(summary.runs.duration_ms.p50)}</span>
              <span className="metric-label">P50 耗时</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{formatDuration(summary.runs.duration_ms.p95)}</span>
              <span className="metric-label">P95 耗时</span>
            </div>
          </div>

          <div className="metric-band" role="region" aria-label="Provider 用量与计算成本">
            <div className="metric-item">
              <span className="metric-value">{summary.provider_calls.total}</span>
              <span className="metric-label">Provider 调用</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{formatTokens(summary.provider_calls.input_tokens)}</span>
              <span className="metric-label">Input Token</span>
            </div>
            <div className="metric-item">
              <span className="metric-value">{formatTokens(summary.provider_calls.output_tokens)}</span>
              <span className="metric-label">Output Token</span>
            </div>
            {hasCalculatedCost ? (
              <div className="metric-item">
                <span className="metric-value cost">{formatCNY(summary.cost.known_amount)}</span>
                <span className="metric-label">已知计算成本</span>
              </div>
            ) : null}
          </div>

          <div className="cost-completeness" role="region" aria-label="成本完整性">
            {summary.cost.calculated_call_count > 0 ? (
              <small>成本已计算 {summary.cost.calculated_call_count} 次调用</small>
            ) : null}
            {summary.cost.unknown_call_count > 0 ? (
              <small className="status-failed">成本未知 {summary.cost.unknown_call_count} 次调用</small>
            ) : null}
            {summary.cost.unknown_by_reason.length > 0 ? (
              <div className="unknown-reasons">
                {summary.cost.unknown_by_reason.map((r) => (
                  <small key={r.reason}>{safeUnknownReason(r.reason)}: {r.count}</small>
                ))}
              </div>
            ) : null}
            {summary.cost.runs_without_provider_calls > 0 ? (
              <small>无外部计费事实 {summary.cost.runs_without_provider_calls} 次运行</small>
            ) : null}
            {hasOnlyUnknown ? (
              <small>暂无可计算金额</small>
            ) : null}
            {hasNoCostData ? (
              <small>当前范围暂无运行</small>
            ) : null}
          </div>

          {summary.runs.errors.length > 0 ? (
            <div className="error-classification" role="region" aria-label="失败分类">
              <h3>失败分类</h3>
              <ul className="error-list">
                {summary.runs.errors.map((e) => (
                  <li key={e.error_code}>
                    <span className="error-label">{safeErrorLabel(e.error_code)}</span>
                    <span className="error-count">{e.count}</span>
                    <button
                      className="error-drill-link"
                      onClick={scrollToFailedRuns}
                      type="button"
                      aria-label={`查看${safeErrorLabel(e.error_code)}的近期异常运行`}
                    >
                      查看近期异常
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : showSummarySpinner ? (
        <div className="runs-state" role="status"><LoaderCircle className="spin" size={18} /><span>正在读取摘要</span></div>
      ) : null}

      <div className="failed-runs-section" role="region" aria-label="最近异常运行" ref={failedSectionRef} tabIndex={-1}>
        <h3>最近异常运行</h3>
        {showFailedError ? (
          <div className="notice error" role="alert">
            <TriangleAlert size={18} />
            <span>{failedRunsError ?? "异常运行读取失败"}</span>
            {/* Fix 3: retry goes through unified refreshAll */}
            <button className="secondary-button" onClick={() => void refreshAll()} type="button">重试</button>
          </div>
        ) : null}
        {showFailedSpinner ? (
          <div className="runs-state" role="status"><LoaderCircle className="spin" size={18} /><span>正在读取异常运行</span></div>
        ) : null}
        {statusExcludesFailures ? (
          <p className="muted">当前筛选不包含异常运行</p>
        ) : null}
        {!statusExcludesFailures && failedRunsLoad === "ready" && failedRuns.length === 0 ? (
          <p className="muted">当前范围暂无异常运行</p>
        ) : null}
        {failedRuns.length > 0 ? (
          <ul className="run-list">
            {failedRuns.map((run) => {
              const expanded = expandedRunId === run.id;
              return (
                <li className="run-row" key={run.id}>
                  <button className="run-summary" onClick={() => void toggleRun(run.id)} type="button" aria-expanded={expanded}>
                    <span className="run-identity">
                      <span className="run-identity-title">
                        <Activity size={16} />
                        <strong>{safeIdentityLabel(run)}</strong>
                      </span>
                      <small>{safeRoleLabel(run.role)} · {STATUS_LABEL[run.status] ?? run.status} · {formatTimestamp(run.created_at)}</small>
                    </span>
                    <span className={`run-status status-${run.status}`}>{STATUS_LABEL[run.status] ?? run.status}</span>
                    {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  </button>
                  {expanded ? (
                    <div className="run-detail">
                      {runDetailError ? <p className="run-detail-error">{runDetailError}</p> : null}
                      {runDetail ? (
                        <>
                          {runDetail.tool_calls.length ? (
                            <ol className="tool-call-list">
                              {runDetail.tool_calls.map((call) => (
                                <li key={`${call.ordinal}-${call.tool_name}`}>
                                  <span className="tool-call-name">{call.ordinal}. {call.tool_name}</span>
                                  <span className="tool-call-status">{call.status === "succeeded" ? "成功" : call.status === "failed" ? "失败" : call.status}</span>
                                  <span className="tool-call-meta">{call.latency_ms != null ? `${call.latency_ms} ms` : "—"}</span>
                                </li>
                              ))}
                            </ol>
                          ) : <p className="muted">暂无阶段记录</p>}
                          <button
                            className="secondary-button"
                            onClick={() => void loadProviderCalls(run.id)}
                            type="button"
                          >
                            {drillRunId === run.id ? "关闭模型调用" : "查看模型调用"}
                          </button>
                          {drillRunId === run.id ? (
                            drillLoading ? (
                              <p className="runs-state inline"><LoaderCircle className="spin" size={14} /><span>正在读取模型调用</span></p>
                            ) : drillError ? (
                              <p className="run-detail-error">{drillError}</p>
                            ) : providerCalls.length > 0 ? (
                              <div className="provider-call-scroll">
                                <table className="provider-call-table">
                                  <thead>
                                    <tr>
                                      <th>阶段</th>
                                      <th>Provider</th>
                                      <th>状态</th>
                                      <th>Token</th>
                                      <th>耗时</th>
                                      <th>成本</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {providerCalls.map((pc) => (
                                      <tr key={pc.id}>
                                        <td>{pc.phase}</td>
                                        <td>{pc.provider}/{pc.model}</td>
                                        <td className={`status-${pc.status}`}>{STATUS_LABEL[pc.status] ?? pc.status}</td>
                                        <td>{pc.input_tokens ?? "?"} / {pc.output_tokens ?? "?"}</td>
                                        <td>{pc.latency_ms != null ? `${pc.latency_ms} ms` : "—"}</td>
                                        {/* Fix 6: safe cost display — no ¥undefined */}
                                        <td>{safeCostDisplay(pc.cost)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : <p className="muted">无模型调用</p>
                          ) : null}
                        </>
                      ) : !runDetailError ? (
                        <p className="runs-state inline"><LoaderCircle className="spin" size={14} /><span>正在读取阶段</span></p>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
