import { BotMessageSquare, LoaderCircle, RefreshCw, Send, Square, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cancelTutorTurn, CourseReader, createTutorSession, createTutorTurn, deleteTutorSession, deleteTutorTurn, fetchLearningMemories, fetchLessonCompletions, fetchMemoryPolicy, fetchTutorSession, fetchTutorSessions, fetchTutorSkill, retryTutorTurn, TutorSession, TutorTeachingSkill, tutorTurnEventsUrl } from "../lib/api";
import RichLearningText from "./RichLearningText";

const active = (status: string) => ["queued", "running", "retry_wait", "cancel_requested"].includes(status);
const errorMessage = (value: unknown) => value instanceof Error ? value.message : String(value);
const pageLabel = (start: number | null, end: number | null) => start == null ? null : start === end || end == null ? `第 ${start} 页` : `第 ${start}-${end} 页`;
const certaintyLabel = (certainty: string | null) => certainty === "confirmed" ? "已确认" : certainty === "provisional" ? "初步判断" : certainty === "insufficient" ? "证据不足" : certainty === "resolved" ? "已改善" : null;

export function TutorPanel({ workspaceId, reader, lessonId, onLessonId, onManageMemory, codeRunId, onCodeRunConsumed }: { workspaceId: string; reader: CourseReader; lessonId: string; onLessonId: (value: string) => void; onManageMemory?: () => void; codeRunId?: string | null; onCodeRunConsumed?: () => void }) {
  const lessons = useMemo(() => reader.version.sections.flatMap((section) => section.lessons
    .filter((lesson) => lesson.published_version)
    .map((lesson) => ({ section, lesson, version: lesson.published_version! }))), [reader]);
  const [sessions, setSessions] = useState<TutorSession[]>([]);
  const [session, setSession] = useState<TutorSession | null>(null);
  const [scope, setScope] = useState<"lesson" | "course">("lesson");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryCount, setMemoryCount] = useState(0);
  const [completionCount, setCompletionCount] = useState(0);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [skill, setSkill] = useState<TutorTeachingSkill | null>(null);
  // Slice 4: science tool authorization per Turn (Spec 004 §6.1, ADR 006 §2.7)
  const [scienceToolAuthorized, setScienceToolAuthorized] = useState(false);
  const [scienceToolAvailable, setScienceToolAvailable] = useState(false);
  // Slice 4 packet 002: code tool authorization per Turn (Spec 004 §8.1)
  const [codeToolAuthorized, setCodeToolAuthorized] = useState(false);
  const [codeToolAvailable, setCodeToolAvailable] = useState(false);
  // Task B: Tutor focus mode removed — the zoom/expand button had no clear
  // value for Tutor (it is not a coding-specific capability) and interacted
  // poorly with practice focus mode. No replacement Tutor full-screen in this round.
  const turnIdempotencyKey = useRef<string | null>(null);
  // Fix 6.2: guards that stop a stale fetch (from an older workspace/course, or
  // landing after unmount) from overwriting the current Tutor state. These refs
  // are intentionally not part of any effect dependency array, so they add no
  // dependency cycle.
  const mountedRef = useRef(true);
  const activeContextRef = useRef({ workspaceId, courseId: reader.course.id, versionId: reader.version.id });
  activeContextRef.current = { workspaceId, courseId: reader.course.id, versionId: reader.version.id };

  const refreshCapabilities = useCallback(async (signal?: AbortSignal) => {
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/api/v1/workspaces/${workspaceId}/mcp-capabilities`, { signal });
    if (!response.ok) throw new Error("capability_status_unavailable");
    const capabilities = await response.json() as Array<{ capability: string; status: string }>;
    const scienceReady = capabilities.find((item) => item.capability === "science_computation")?.status === "ready";
    const codeReady = capabilities.find((item) => item.capability === "code_execution")?.status === "ready";
    setScienceToolAvailable(scienceReady);
    setCodeToolAvailable(codeReady);
    return { scienceReady, codeReady };
  }, [workspaceId]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchTutorSkill(workspaceId, controller.signal).then((capability) => setSkill(capability.teaching_skill)).catch(() => {
      if (!controller.signal.aborted) setSkill(null);
    });
    const refresh = () => {
      void refreshCapabilities(controller.signal).catch(() => {
        if (!controller.signal.aborted) {
          setScienceToolAvailable(false);
          setCodeToolAvailable(false);
        }
      });
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") refresh();
    };
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refreshCapabilities, workspaceId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Fix 6.1: when a capability goes ready -> unavailable, its per-Turn
  // authorization is cleared so the toggle can never be disabled-but-checked.
  useEffect(() => { if (!scienceToolAvailable) setScienceToolAuthorized(false); }, [scienceToolAvailable]);
  useEffect(() => { if (!codeToolAvailable) setCodeToolAuthorized(false); }, [codeToolAvailable]);

  const refreshSessions = useCallback(async () => {
    // Fix 6.2: capture the context this fetch belongs to. A response that lands
    // after the workspace/course changed — or after unmount — is dropped instead
    // of overwriting the current state, and a stale fetch's failure is swallowed.
    const context = { workspaceId, courseId: reader.course.id, versionId: reader.version.id };
    const stale = () => !mountedRef.current
      || activeContextRef.current.workspaceId !== context.workspaceId
      || activeContextRef.current.courseId !== context.courseId
      || activeContextRef.current.versionId !== context.versionId;
    let items: TutorSession[];
    try {
      items = await fetchTutorSessions(context.workspaceId, context.courseId, context.versionId);
    } catch (value) {
      if (stale()) return;
      throw value;
    }
    if (stale()) return;
    setSessions(items);
    setSession((current) => items.find((item) => item.id === current?.id) ?? items[0] ?? null);
  }, [reader.course.id, reader.version.id, workspaceId]);

  useEffect(() => {
    setSession(null);
    void refreshSessions().catch((value) => setError(errorMessage(value)));
  }, [lessons, refreshSessions]);

  const sessionId = session?.id;
  const latestTurn = session ? session.turns[session.turns.length - 1] : undefined;
  const latestTurnId = latestTurn?.id;
  const latestTurnStatus = latestTurn?.status;
  const selectedLesson = lessons.find((item) => item.lesson.id === lessonId);
  const visibleTurns = session?.turns.filter((turn) => scope === "course"
    ? turn.scope === "course"
    : turn.scope === "lesson" && turn.lesson_version_id === selectedLesson?.version.id) ?? [];
  const latestVisibleTurn = visibleTurns[visibleTurns.length - 1];
  useEffect(() => {
    setScienceToolAuthorized(false);
    setCodeToolAuthorized(false);
    turnIdempotencyKey.current = null;
  }, [lessonId, scope, workspaceId]);

  useEffect(() => {
    // Fix 6.2: drop late results from an older workspace/course/scope or after
    // unmount so they never overwrite the current memory/completion state.
    let cancelled = false;
    void Promise.all([fetchLearningMemories(workspaceId), fetchLessonCompletions(workspaceId, reader.course.id), fetchMemoryPolicy(workspaceId)])
      .then(([memories, completions, policy]) => {
        if (cancelled) return;
        setMemoryEnabled(policy.tutor_use_enabled);
        setMemoryCount(policy.tutor_use_enabled ? memories.filter((memory) => memory.status === "active" && memory.course_id === reader.course.id && (scope === "course" || memory.lesson_id === lessonId)).slice(0, 5).length : 0);
        setCompletionCount(policy.tutor_use_enabled ? completions.filter((completion) => completion.course_version_id === reader.version.id && (scope === "course" || completion.lesson_version_id === selectedLesson?.version.id)).slice(0, 10).length : 0);
      })
      .catch((value) => { if (!cancelled) setError(errorMessage(value)); });
    return () => { cancelled = true; };
  }, [lessonId, reader.course.id, reader.version.id, scope, selectedLesson?.version.id, workspaceId]);
  useEffect(() => {
    if (!sessionId || !latestTurnId || !latestTurnStatus || !active(latestTurnStatus)) return;
    // Slice 2B Batch B: the EventSource is opened only once React observes the
    // active Turn. If the worker finishes before that, the completion event is
    // lost and the page would stay on a queued/running snapshot. The polling
    // below is a bounded fallback over the authoritative session; the SSE
    // channel above remains the primary live update path.
    // `cancelled` is the request-sequence guard: it is flipped in cleanup, so a
    // response that lands after the session/turn/workspace changed (or after
    // unmount / terminal state) is discarded instead of overwriting new state.
    let cancelled = false;
    const refresh = () => void fetchTutorSession(workspaceId, sessionId)
      .then((next) => { if (!cancelled) setSession(next); })
      .catch(() => undefined);
    const source = new EventSource(tutorTurnEventsUrl(workspaceId, latestTurnId));
    ["turn.started", "turn.progress", "answer.delta", "citation.available", "turn.completed", "turn.failed", "turn.canceled"].forEach((name) => source.addEventListener(name, refresh));
    refresh();                                        // immediate refresh on entering active state
    const timer = window.setInterval(refresh, 2_500);  // short-interval fallback poll
    // Explicit wall-time bound: stop polling even if the Turn never reaches a
    // terminal state we observe. The SSE channel keeps running regardless, and
    // the effect tears down on terminal/session/turn/workspace change/unmount.
    const hardStop = window.setTimeout(() => window.clearInterval(timer), 120_000);
    return () => {
      cancelled = true;
      source.close();
      window.clearInterval(timer);
      window.clearTimeout(hardStop);
    };
  }, [latestTurnId, latestTurnStatus, sessionId, workspaceId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!question.trim()) return; setBusy(true); setError(null);
    try {
      if (scienceToolAuthorized || codeToolAuthorized) {
        const availability = await refreshCapabilities();
        if (scienceToolAuthorized && !availability.scienceReady) throw new Error("science_tool_unavailable");
        if (codeToolAuthorized && !availability.codeReady) throw new Error("code_tool_unavailable");
      }
      if (scope === "lesson" && !selectedLesson) throw new Error("请选择当前课程中的有效课节");
      let current = session;
      if (!current) {
        const accepted = window.confirm(memoryEnabled
          ? "问题、必要的课程资料片段，以及启用的学习记忆和课节完成摘要将发送给当前配置的外部 AI，所选教学方法会处理这些内容。是否继续？"
          : "问题和必要的课程资料片段将发送给当前配置的外部 AI，所选教学方法会处理这些内容。是否继续？");
        if (!accepted) return;
        current = await createTutorSession(workspaceId, reader.course.id, reader.version.id, true);
      }
      const selected = selectedLesson;
      turnIdempotencyKey.current ??= crypto.randomUUID();
      const idempotencyKey = turnIdempotencyKey.current;
      const turnPayload = scope === "course"
        ? { question: question.trim(), scope, science_tool_authorized: scienceToolAuthorized, code_tool_authorized: codeToolAuthorized, code_run_id: codeRunId ?? undefined }
        : { question: question.trim(), scope, section_id: selected?.section.id, lesson_id: selected?.lesson.id, lesson_version_id: selected?.version.id, science_tool_authorized: scienceToolAuthorized, code_tool_authorized: codeToolAuthorized, code_run_id: codeRunId ?? undefined };
      await createTutorTurn(workspaceId, current.id, turnPayload, idempotencyKey);
      // Fix 6.3: consume/clear the key the moment createTutorTurn succeeds — the
      // server has now bound it to this Turn. Clearing before the session read
      // means a later read failure can never make the next submit reuse an
      // already-consumed key. If createTutorTurn threw above, the catch keeps the
      // key so the same user action can safely retry.
      turnIdempotencyKey.current = null;
      setSession(await fetchTutorSession(workspaceId, current.id));
      setQuestion(""); setScienceToolAuthorized(false); setCodeToolAuthorized(false);
      // Per §4.3: code_run_id is consumed after send — next Turn does not inherit
      onCodeRunConsumed?.();
      await refreshSessions();
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const mutateTurn = async (work: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await work(); if (sessionId) setSession(await fetchTutorSession(workspaceId, sessionId)); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const removeSession = async () => {
    if (!sessionId) return; setBusy(true); setError(null);
    try { await deleteTutorSession(workspaceId, sessionId); setSession(null); await refreshSessions(); }
    catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  const removeTurn = async (turnId: string) => {
    if (!sessionId || !window.confirm("删除这条问答记录？问题、回答、引用和运行记录都将被永久删除。")) return;
    setBusy(true); setError(null);
    try {
      await deleteTutorTurn(workspaceId, turnId);
      setSession(await fetchTutorSession(workspaceId, sessionId));
      await refreshSessions();
    } catch (value) { setError(errorMessage(value)); }
    finally { setBusy(false); }
  };

  // Task B: Tutor focus mode removed — no focused state, no Escape handler, no zoom button.

  return <aside className="tutor-panel" aria-label="课程 Tutor">
    <header><div><span className="eyebrow">受控 Tutor</span><h3><BotMessageSquare size={18} />课程问答</h3></div><div className="header-actions">{session ? <button className="icon-button" disabled={busy} onClick={() => void removeSession()} title="删除当前 Tutor Session" type="button"><Trash2 /></button> : null}</div></header>
    <div className="tutor-meta"><span>课程版本 {reader.version.version_number}</span><span>{session ? `${session.provider} / ${session.model}` : "尚未创建 Session"}</span>{latestVisibleTurn?.status === "succeeded" ? <span className="tool-usage">代码 {latestVisibleTurn.code_tool_call_count} 次 / 科学 {latestVisibleTurn.science_tool_call_count} 次</span> : null}</div>
    <div className="tutor-skill-meta">教学方法：{skill ? `${skill.display_name} v${skill.version}` : "—"}</div>
    <div className="tutor-memory-status">{memoryEnabled ? <>当前范围可选 {memoryCount} 条薄弱点记忆、{completionCount} 条课节完成记录{latestVisibleTurn?.status === "succeeded" ? `；最近一次实际使用 ${latestVisibleTurn.memory_count} 条、${latestVisibleTurn.completion_count} 条` : ""}</> : "学习记忆与课节完成记录未用于 Tutor"}{onManageMemory ? <button className="text-button" onClick={onManageMemory} type="button">管理</button> : null}</div>
    {sessions.length ? <select aria-label="Tutor Session" onChange={(event) => setSession(sessions.find((item) => item.id === event.target.value) ?? null)} value={sessionId ?? ""}>{sessions.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")}</option>)}</select> : null}
    <div className="scope-control"><button className={scope === "lesson" ? "active" : ""} onClick={() => { turnIdempotencyKey.current = null; setScope("lesson"); }} type="button">当前课节</button><button className={scope === "course" ? "active" : ""} onClick={() => { turnIdempotencyKey.current = null; setScope("course"); }} type="button">整门课程</button></div>
    {scope === "lesson" ? <select aria-label="Tutor 课节" onChange={(event) => { turnIdempotencyKey.current = null; onLessonId(event.target.value); }} value={lessonId}>{lessons.map(({ lesson }) => <option key={lesson.id} value={lesson.id}>{lesson.title}</option>)}</select> : null}
    <div className="tutor-history">{visibleTurns.length ? visibleTurns.map((turn) => {
      const citations = turn.citations ?? [];
      const numbers = new Map(citations.map((citation, index) => [citation.citation_id, index + 1]));
      return <article key={turn.id}><p className="tutor-question">{turn.question}</p>{turn.answer_blocks?.map((block) => <div className={`tutor-answer ${block.type}`} key={block.block_key}>{block.type === "learning_diagnosis" && certaintyLabel(block.certainty) ? <strong className="certainty-marker">{certaintyLabel(block.certainty)}：</strong> : null}<RichLearningText content={block.text} compact />{block.citation_ids.length ? <small className="citation-markers">{block.citation_ids.map((id) => numbers.has(id) ? <span key={id}>[{numbers.get(id)}]</span> : null)}</small> : null}</div>)}{citations.map((citation) => <small className="tutor-citation" key={citation.citation_id}>{numbers.get(citation.citation_id)}. {[citation.document_name, ...citation.heading_path, pageLabel(citation.page_start, citation.page_end)].filter(Boolean).join(" > ")}</small>)}<footer><span className="tutor-skill-badge" title={turn.teaching_skill ? `${turn.teaching_skill.display_name} v${turn.teaching_skill.version}` : "Slice 3 前的历史 Turn"}>{turn.teaching_skill ? `${turn.teaching_skill.display_name} v${turn.teaching_skill.version}` : "基础 Tutor（历史）"}</span><span>{turn.status}</span>{active(turn.status) ? <button disabled={busy} onClick={() => void mutateTurn(() => cancelTutorTurn(workspaceId, turn.id))} type="button"><Square size={13} />取消</button> : <button className="icon-button" disabled={busy} onClick={() => void removeTurn(turn.id)} title="删除这条问答" type="button"><Trash2 size={14} /></button>}{["failed", "canceled", "queue_failed"].includes(turn.status) ? <button disabled={busy} onClick={() => void mutateTurn(() => retryTutorTurn(workspaceId, turn.id))} type="button"><RefreshCw size={13} />重试</button> : null}</footer>{turn.error_message ? <p className="form-error">{turn.error_message}</p> : null}</article>;
    }) : <p className="muted">当前范围还没有问答记录。</p>}</div>
    <form onSubmit={submit}><textarea maxLength={8000} onChange={(event) => { turnIdempotencyKey.current = null; setQuestion(event.target.value); }} placeholder="输入问题" rows={3} value={question} />
    {/* Slice 4: science tool toggle per Turn (Spec 004 §6.1, ADR 006 §2.7) */}
    <div className="science-tool-toggle">
      <label>
        <input type="checkbox" checked={scienceToolAuthorized} onChange={(e) => setScienceToolAuthorized(e.target.checked)} disabled={!scienceToolAvailable} />
        允许本次使用科学工具
      </label>
      {scienceToolAvailable && scienceToolAuthorized && <small>必要的问题内容将发送给外部 Wolfram 科学计算服务。本次最多调用 3 次。</small>}
      {!scienceToolAvailable && <small className="muted">科学工具未启用</small>}
    </div>
    {/* Slice 4 packet 002: code tool toggle per Turn (Spec 004 §8.1) */}
    <div className="code-tool-toggle">
      <label>
        <input type="checkbox" checked={codeToolAuthorized} onChange={(e) => setCodeToolAuthorized(e.target.checked)} disabled={!codeToolAvailable} />
        允许本次运行代码
      </label>
      {codeToolAvailable && codeToolAuthorized && <small>代码将发送给执行服务运行。本次最多调用 2 次。</small>}
      {!codeToolAvailable && <small className="muted">代码执行未启用</small>}
    </div>
    <button className="primary-button" disabled={busy || !question.trim() || (scope === "lesson" && !selectedLesson) || Boolean(latestTurn && active(latestTurn.status))} type="submit">{busy ? <LoaderCircle className="spin" /> : <Send />}发送</button></form>
    {!session ? <small>首次发送前将确认使用固定课程版本和当前 provider 处理问题、短期历史及资料片段。</small> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </aside>;
}
