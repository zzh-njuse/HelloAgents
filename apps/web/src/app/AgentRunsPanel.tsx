import { Activity, ChevronDown, ChevronRight, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  AgentRunDetail,
  AgentRunQuery,
  AgentRunRole,
  AgentRunStatus,
  AgentRunSummary,
  Course,
  fetchAgentRun,
  fetchAgentRuns,
  fetchCourses
} from "../lib/api";

type LoadState = "loading" | "ready" | "error";

const ROLE_LABEL: Record<AgentRunRole, string> = {
  course_architect: "课程架构",
  lesson_writer: "课节撰写",
  tutor: "辅导",
  exercise_author: "练习生成",
  answer_grader: "练习评分",
  scientific_solution_grader: "科学题验证",
  code_execution: "代码执行",
};

const STATUS_LABEL: Record<AgentRunStatus, string> = {
  running: "进行中",
  succeeded: "成功",
  failed: "失败",
  canceled: "已取消"
};

const COURSE_JOB_LABEL: Record<string, string> = {
  course_outline: "课程大纲",
  lesson_draft: "课节草稿"
};

const PRACTICE_JOB_LABEL: Record<string, string> = {
  generate_set: "练习生成",
  grade_attempt: "练习评分"
};

// Only stable, non-sensitive short descriptions. Never surfaces server logs,
// stack traces, prompts or provider configuration.
const ERROR_LABEL: Record<string, string> = {
  generation_canceled: "运行已取消",
  generation_internal_error: "运行出现内部错误",
  generation_provider_unavailable: "模型服务暂不可用",
  generation_provider_unconfigured: "模型服务未配置",
  generation_budget_exceeded: "超出运行预算",
  invalid_agent_artifact: "生成结果不符合规范",
  insufficient_evidence: "资料证据不足",
  unknown_citation: "引用校验失败",
  source_snapshot_stale: "课程来源已变化",
  queue_unavailable: "任务队列暂不可用",
  queue_failed: "任务队列失败"
};

const TOOL_LABEL: Record<string, string> = {
  CourseEvidenceSearch: "证据检索",
  TutorEvidenceSearch: "证据检索",
  SubmitCourseOutline: "提交课程大纲",
  SubmitLessonDraft: "提交课节草稿"
};

const RUNS_LOAD_ERROR = "运行记录读取失败，请稍后重试";
const DETAIL_LOAD_ERROR = "运行阶段读取失败，请稍后重试";
const isKnownRole = (role: string): role is AgentRunRole =>
  Object.prototype.hasOwnProperty.call(ROLE_LABEL, role);
const isKnownStatus = (status: string): status is AgentRunStatus =>
  Object.prototype.hasOwnProperty.call(STATUS_LABEL, status);
const safeRoleLabel = (role: string): string => {
  if (isKnownRole(role)) return ROLE_LABEL[role];
  return "其他运行";
};
const safeErrorText = (code: string | null): string | null => {
  if (!code) return null;
  return ERROR_LABEL[code] ?? "运行出现问题";
};
const toolLabel = (name: string) => TOOL_LABEL[name] ?? name;
const isRunning = (status: string) => status === "running";

function identityLabel(run: AgentRunSummary): string {
  const identity = run.identity;
  if (identity.course_deleted) return "已删除对象";
  switch (identity.kind) {
    case "course_generation": {
      const jobType = identity.job_type ? COURSE_JOB_LABEL[identity.job_type] ?? "课程生成" : "课程生成";
      const parts = [jobType, identity.course_title, identity.lesson_title].filter(Boolean) as string[];
      return parts.length ? parts.join(" · ") : "课程生成";
    }
    case "tutor": {
      const scope = identity.tutor_scope === "lesson" ? "本课辅导" : "本课程辅导";
      const parts = [scope, identity.course_title, identity.lesson_title].filter(Boolean) as string[];
      return parts.length ? parts.join(" · ") : "辅导";
    }
    case "practice": {
      const jobType = identity.job_type ? PRACTICE_JOB_LABEL[identity.job_type] ?? "练习" : "练习";
      const parts = [jobType, identity.course_title, identity.lesson_title].filter(Boolean) as string[];
      return parts.length ? parts.join(" · ") : "练习";
    }
    case "code_execution": {
      const lang = identity.code_language ?? "";
      const parts = ["代码执行", lang, identity.course_title, identity.lesson_title].filter(Boolean) as string[];
      return parts.length ? parts.join(" · ") : "代码执行";
    }
    case "unknown":
      return "其他运行";
    default:
      return "其他运行";
  }
}

function tokenLabel(run: AgentRunSummary): string {
  if (run.input_tokens === null && run.output_tokens === null) return "token 未报告";
  const input = run.input_tokens === null ? "?" : String(run.input_tokens);
  const output = run.output_tokens === null ? "?" : String(run.output_tokens);
  return `入 ${input} / 出 ${output}`;
}

function durationLabel(run: AgentRunSummary): string {
  if (run.duration_seconds !== null) return `${run.duration_seconds.toFixed(1)} s`;
  if (isRunning(run.status)) return "进行中";
  return "—";
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
}

export function AgentRunsPanel({ workspaceId }: { workspaceId: string }) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [filterCourse, setFilterCourse] = useState("");
  const [filterRole, setFilterRole] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [coursesError, setCoursesError] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, AgentRunDetail>>({});
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({});
  const runsRequest = useRef(0);
  const detailRequest = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setCourses([]);
    setCoursesError(false);
    fetchCourses(workspaceId, controller.signal)
      .then((next) => { if (!cancelled) setCourses(next); })
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (!cancelled) setCoursesError(true);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [workspaceId]);

  const refresh = useCallback(
    async (signal?: AbortSignal, silent = false) => {
      const request = ++runsRequest.current;
      if (!silent) {
        setLoadState("loading");
        setRuns([]);
      }
      const query: AgentRunQuery = {};
      if (filterCourse) query.course_id = filterCourse;
      if (isKnownRole(filterRole)) query.role = filterRole;
      if (isKnownStatus(filterStatus)) query.status = filterStatus;
      try {
        const next = await fetchAgentRuns(workspaceId, query, signal);
        if (request !== runsRequest.current) return;
        setRuns(next);
        setLoadState("ready");
        setError(null);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (request !== runsRequest.current) return;
        if (!silent) {
          setLoadState("error");
          setError(RUNS_LOAD_ERROR);
        }
      }
    },
    [workspaceId, filterCourse, filterRole, filterStatus]
  );

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const hasActive = runs.some((run) => isRunning(run.status));
  useEffect(() => {
    if (!hasActive) return;
    const controller = new AbortController();
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      await refresh(controller.signal, true);
      if (expandedId) {
        const request = ++detailRequest.current;
        await fetchAgentRun(workspaceId, expandedId, controller.signal)
          .then((detail) => {
            if (request !== detailRequest.current) return;
            setDetails((current) => ({ ...current, [expandedId]: detail }));
            setDetailErrors((current) => {
              const next = { ...current };
              delete next[expandedId];
              return next;
            });
          })
          .catch((err) => {
            if (err instanceof DOMException && err.name === "AbortError") return;
            if (request !== detailRequest.current) return;
            setDetailErrors((current) => ({ ...current, [expandedId]: DETAIL_LOAD_ERROR }));
          });
      }
      polling = false;
    };
    const timer = window.setInterval(() => { void poll(); }, 2000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [hasActive, expandedId, workspaceId, refresh]);

  const toggleRun = useCallback(
    async (runId: string) => {
      setExpandedId((current) => (current === runId ? null : runId));
      if (details[runId]) return;
      const request = ++detailRequest.current;
      setDetailErrors((current) => {
        const next = { ...current };
        delete next[runId];
        return next;
      });
      try {
        const detail = await fetchAgentRun(workspaceId, runId);
        if (request !== detailRequest.current) return;
        setDetails((current) => ({ ...current, [runId]: detail }));
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (request !== detailRequest.current) return;
        setDetailErrors((current) => ({ ...current, [runId]: DETAIL_LOAD_ERROR }));
      }
    },
    [workspaceId, details]
  );

  const showSpinner = loadState === "loading" && runs.length === 0;
  const showError = loadState === "error" && runs.length === 0;
  const showEmpty = loadState === "ready" && runs.length === 0;

  return (
    <section className="agent-runs-panel" aria-labelledby="agent-runs-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">运行记录</span>
          <h2 id="agent-runs-title">运行记录</h2>
        </div>
        <button
          aria-label="刷新运行记录"
          className="icon-button"
          disabled={loadState === "loading"}
          onClick={() => void refresh()}
          title="刷新运行记录"
          type="button"
        >
          {loadState === "loading" ? <LoaderCircle className="spin" /> : <RefreshCw />}
        </button>
      </div>

      <div className="runs-filters">
        <label>
          课程
          <select aria-label="按课程筛选" onChange={(event) => setFilterCourse(event.target.value)} value={filterCourse}>
            <option value="">全部课程</option>
            {courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
          </select>
        </label>
        <label>
          角色
          <select aria-label="按角色筛选" onChange={(event) => setFilterRole(event.target.value)} value={filterRole}>
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
          <select aria-label="按状态筛选" onChange={(event) => setFilterStatus(event.target.value)} value={filterStatus}>
            <option value="">全部状态</option>
            <option value="running">进行中</option>
            <option value="succeeded">成功</option>
            <option value="failed">失败</option>
            <option value="canceled">已取消</option>
          </select>
        </label>
      </div>
      {coursesError ? <p className="muted" role="status">课程筛选暂不可用，运行记录仍可查看</p> : null}

      {showSpinner ? (
        <div className="runs-state"><LoaderCircle className="spin" size={18} /><span>正在读取运行记录</span></div>
      ) : null}
      {showError ? (
        <div className="notice error" role="alert">
          <TriangleAlert size={18} />
          <span>{error ?? "运行记录读取失败"}</span>
          <button className="secondary-button" onClick={() => void refresh()} type="button">重试</button>
        </div>
      ) : null}
      {showEmpty ? (
        <div className="runs-state"><Activity size={18} /><span>当前筛选下没有运行记录</span></div>
      ) : null}

      {runs.length > 0 ? (
        <ul className="run-list">
          {runs.map((run) => {
            const expanded = expandedId === run.id;
            const detail = details[run.id];
            const detailError = detailErrors[run.id];
            const errorText = safeErrorText(run.error_code);
            return (
              <li className="run-row" key={run.id}>
                <button className="run-summary" onClick={() => void toggleRun(run.id)} type="button" aria-expanded={expanded} aria-controls={`run-detail-${run.id}`}>
                  <span className="run-identity">
                    <span className="run-identity-title">
                      {run.role === "tutor" ? <Activity size={16} /> : <RefreshCw size={16} />}
                      <strong>{identityLabel(run)}</strong>
                    </span>
                    <small>{safeRoleLabel(run.role)} · 第 {run.attempt_number} 次</small>
                  </span>
                  <span className="run-metrics">
                    <small>{tokenLabel(run)}</small>
                    <small>{formatTimestamp(run.created_at)}</small>
                    <small>耗时 {durationLabel(run)}</small>
                  </span>
                  <span className={`run-status status-${run.status}`}>{STATUS_LABEL[run.status]}</span>
                  {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                </button>
                {expanded ? (
                  <div className="run-detail" id={`run-detail-${run.id}`}>
                    {errorText ? <p className="run-detail-error">{errorText}</p> : null}
                    {detailError ? <p className="run-detail-error">{detailError}</p> : null}
                    {detail ? (
                      detail.tool_calls.length ? (
                        <ol className="tool-call-list">
                          {detail.tool_calls.map((call) => (
                            <li key={`${call.ordinal}-${call.tool_name}`}>
                              <span className="tool-call-name">{call.ordinal}. {toolLabel(call.tool_name)}</span>
                              <span className="tool-call-status">{call.status === "succeeded" ? "成功" : call.status === "failed" ? "失败" : call.status}</span>
                              <span className="tool-call-meta">{call.result_count != null ? `${call.result_count} 条` : "—"}</span>
                              <span className="tool-call-meta">{call.latency_ms != null ? `${call.latency_ms} ms` : "—"}</span>
                              {call.error_code ? <small>{safeErrorText(call.error_code)}</small> : null}
                            </li>
                          ))}
                        </ol>
                      ) : <p className="muted">暂无阶段记录</p>
                    ) : !detailError ? (
                      <p className="runs-state inline"><LoaderCircle className="spin" size={14} /><span>正在读取阶段</span></p>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
