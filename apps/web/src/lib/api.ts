const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export interface ReadinessCheck {
  ok: boolean;
  detail: string;
}

export interface Readiness {
  status: "ready" | "degraded";
  checks: {
    postgres: ReadinessCheck;
    qdrant: ReadinessCheck;
    redis: ReadinessCheck;
    storage: ReadinessCheck;
  };
}

export interface SystemInfo {
  app_name: string;
  environment: string;
  storage: { configured: boolean };
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreate {
  name: string;
  description?: string | null;
}

export interface WorkspaceDeletionImpact {
  document_count: number;
  course_count: number;
  active_job_count: number;
  tutor_session_count: number;
}

export interface WorkspaceDeletionJob {
  id: string;
  workspace_id: string;
  status: "queued" | "queue_failed" | "running" | "retry_wait" | "succeeded" | "failed";
  attempt_count: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface IngestionJob {
  id: string;
  workspace_id: string;
  document_version_id: string | null;
  status: "queued" | "queue_failed" | "running" | "retry_wait" | "succeeded" | "failed" | "canceled";
  attempt_count: number;
  error_message: string | null;
  next_attempt_at: string | null;
}

export interface DocumentUpload {
  document: { id: string; display_name: string };
  job: IngestionJob;
}

export interface DocumentSummary {
  id: string;
  display_name: string;
  updated_at: string;
  current_version: { byte_size: number; mime_type: string; processing_status: string } | null;
  latest_job: IngestionJob | null;
}

export interface RetrievalResult {
  score: number;
  text: string;
  citation: { chunk_id: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number };
}

export interface BatchItem {
  id: string;
  client_ordinal: number;
  display_filename: string;
  declared_byte_size: number;
  status: string;
  error_message: string | null;
}

export interface IngestionBatch {
  id: string;
  status: string;
  item_count: number;
  ready_count: number;
  failed_count: number;
  canceled_count: number;
  items: BatchItem[];
}

export interface AnswerResponse {
  trace_id: string;
  status: "succeeded" | "insufficient_evidence" | "failed";
  claims: { text: string; citation_ids: string[] }[];
  citations: { citation_id: string; chunk_id: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number; text: string }[];
  limitations: string[];
  model: string | null;
}

export interface Course {
  id: string;
  workspace_id: string;
  title: string;
  goal: string;
  audience: string | null;
  current_active_version_id: string | null;
  source_degraded: boolean;
  source_count: number;
  published_lesson_count: number;
  pending_lesson_count: number;
  latest_job: CourseGenerationJob | null;
}

export interface CourseGenerationJob {
  id: string;
  course_id: string;
  course_version_id: string | null;
  lesson_id: string | null;
  job_type: "course_outline" | "lesson_draft";
  output_language: "zh-CN" | "en";
  status: string;
  attempt_count: number;
  error_message: string | null;
}

export interface LessonCitation { citation_id: string; block_key: string; document_id: string; document_version_id: string; chunk_id: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number; page_start: number | null; page_end: number | null; available: boolean }
export interface LessonVersion { id: string; version_number: number; status: string; title: string; learning_objectives: string[]; blocks: { block_key: string; type: string; text: string; citation_ids: string[] }[]; citations?: LessonCitation[] }
export interface CourseLesson { id: string; title: string; objective: string; current_published_version_id: string | null; versions?: LessonVersion[]; published_version?: LessonVersion | null }
export interface CourseVersion { id: string; version_number: number; status: string; title: string; summary: string | null; source_degraded: boolean; sections: { id: string; title: string; objective: string; lessons: CourseLesson[] }[] }
export interface CourseDetail { course: Course; versions: CourseVersion[] }
export interface CourseReader { course: Course; version: CourseVersion }
export interface LessonCompletion { id: string; course_id: string; course_version_id: string; lesson_id: string; lesson_version_id: string; lesson_title: string; is_current_version: boolean; completed_at: string }
export interface TutorCitation { citation_id: string; block_key: string; document_name: string; heading_path: string[]; start_offset: number; end_offset: number; page_start: number | null; page_end: number | null }
export interface TutorTeachingSkill { id: string; display_name: string; version: string }
export interface TutorTurn { id: string; session_id: string; ordinal: number; attempt_number: number; status: string; question: string; scope: "course" | "lesson"; section_id: string | null; lesson_id: string | null; lesson_version_id: string | null; answer_blocks: { block_key: string; type: string; text: string; citation_ids: string[]; certainty: string | null }[] | null; citations: TutorCitation[]; error_code: string | null; error_message: string | null; created_at: string; completed_at: string | null; memory_count: number; completion_count: number; teaching_skill: TutorTeachingSkill | null; science_tool_used: boolean; science_tool_call_count: number; code_tool_used: boolean; code_tool_call_count: number }
export interface TutorSession { id: string; workspace_id: string; course_id: string; course_version_id: string; status: string; provider: string; model: string; created_at: string; turns: TutorTurn[] }
export interface TutorSkillCapability { teaching_skill: TutorTeachingSkill }

// Stage 5 Slice 1A: seven known roles. The response role field is a plain
// string so unknown historical values are preserved rather than rejected.
export type AgentRunRole = "course_architect" | "lesson_writer" | "tutor" | "exercise_author" | "answer_grader" | "scientific_solution_grader" | "code_execution";
export type AgentRunStatus = "running" | "succeeded" | "failed" | "canceled";

export interface AgentRunIdentity {
  kind: "course_generation" | "tutor" | "practice" | "code_execution" | "unknown";
  job_type: string | null;
  course_id: string | null;
  course_title: string | null;
  course_deleted: boolean;
  lesson_id: string | null;
  lesson_title: string | null;
  tutor_scope: string | null;
  code_language: string | null;
}

export interface AgentToolCallRead {
  tool_name: string;
  ordinal: number;
  status: string;
  result_count: number | null;
  latency_ms: number | null;
  error_code: string | null;
  created_at: string;
}

export interface AgentRunSummary {
  id: string;
  // Role is a plain string to safely handle unknown historical values.
  // Use AgentRunRole for known filter values.
  role: string;
  status: AgentRunStatus;
  attempt_number: number;
  step_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  error_code: string | null;
  identity: AgentRunIdentity;
}

export interface AgentRunDetail extends AgentRunSummary {
  tool_calls: AgentToolCallRead[];
}

export interface AgentRunQuery {
  course_id?: string;
  role?: AgentRunRole;
  status?: AgentRunStatus;
  limit?: number;
}

export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  return request<Readiness>("/ready", { signal });
}

export async function fetchSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  return request<SystemInfo>("/api/v1/system/info", { signal });
}

export async function fetchWorkspaces(signal?: AbortSignal): Promise<Workspace[]> {
  return request<Workspace[]>("/api/v1/workspaces", { signal });
}

export async function createWorkspace(payload: WorkspaceCreate): Promise<Workspace> {
  return request<Workspace>("/api/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchWorkspaceDeletionImpact(workspaceId: string): Promise<WorkspaceDeletionImpact> {
  return request<WorkspaceDeletionImpact>(`/api/v1/workspaces/${workspaceId}/deletion-impact`);
}

export async function deleteWorkspace(workspaceId: string, confirmationName: string, idempotencyKey: string = crypto.randomUUID()): Promise<WorkspaceDeletionJob> {
  return request<WorkspaceDeletionJob>(`/api/v1/workspaces/${workspaceId}/deletion`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ confirmation_name: confirmationName })
  });
}

export async function fetchWorkspaceDeletionJob(jobId: string): Promise<WorkspaceDeletionJob> {
  return request<WorkspaceDeletionJob>(`/api/v1/workspaces/deletion-jobs/${jobId}`);
}

export async function retryWorkspaceDeletion(jobId: string): Promise<WorkspaceDeletionJob> {
  return request<WorkspaceDeletionJob>(`/api/v1/workspaces/deletion-jobs/${jobId}/retry`, { method: "POST" });
}

export async function uploadDocument(workspaceId: string, file: File): Promise<DocumentUpload> {
  const form = new FormData();
  form.append("file", file);
  return request<DocumentUpload>(`/api/v1/workspaces/${workspaceId}/documents`, { method: "POST", body: form });
}

export async function uploadDocumentBatch(workspaceId: string, files: File[], idempotencyKey: string): Promise<IngestionBatch> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches`, {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: form
  });
}

export async function fetchDocumentBatch(workspaceId: string, batchId: string): Promise<IngestionBatch> {
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches/${batchId}`);
}

export async function retryDocumentBatch(workspaceId: string, batchId: string): Promise<IngestionBatch> {
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches/${batchId}/retry`, { method: "POST" });
}

export async function cancelDocumentBatch(workspaceId: string, batchId: string): Promise<IngestionBatch> {
  return request<IngestionBatch>(`/api/v1/workspaces/${workspaceId}/document-batches/${batchId}/cancel`, { method: "POST" });
}

export async function fetchDocuments(workspaceId: string, signal?: AbortSignal): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>(`/api/v1/workspaces/${workspaceId}/documents`, { signal });
}

export async function deleteDocument(workspaceId: string, documentId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/v1/workspaces/${workspaceId}/documents/${documentId}`, { method: "DELETE" });
}

export async function fetchDocumentCourseImpact(workspaceId: string, documentId: string): Promise<{ affected_course_count: number }> {
  return request(`/api/v1/workspaces/${workspaceId}/documents/${documentId}/course-impact`);
}

export async function retryIngestionJob(workspaceId: string, jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/v1/workspaces/${workspaceId}/ingestion-jobs/${jobId}/retry`, { method: "POST" });
}

export async function fetchIngestionJob(workspaceId: string, jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/v1/workspaces/${workspaceId}/ingestion-jobs/${jobId}`);
}

export async function searchMaterials(workspaceId: string, query: string): Promise<{ results: RetrievalResult[] }> {
  return request<{ results: RetrievalResult[] }>(`/api/v1/workspaces/${workspaceId}/rag/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: 5 })
  });
}

export async function answerMaterials(workspaceId: string, question: string): Promise<AnswerResponse> {
  return request<AnswerResponse>(`/api/v1/workspaces/${workspaceId}/rag/answer`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, top_k: 5 })
  });
}

export async function fetchCourses(workspaceId: string, signal?: AbortSignal): Promise<Course[]> {
  return request<Course[]>(`/api/v1/workspaces/${workspaceId}/courses`, { signal });
}

export async function createCourse(workspaceId: string, payload: { title: string; goal: string; audience?: string; document_ids: string[]; output_language: "zh-CN" | "en" }): Promise<{ course: Course; job: CourseGenerationJob }> {
  return request(`/api/v1/workspaces/${workspaceId}/courses`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ ...payload, external_processing_ack: true }) });
}

export async function fetchCourse(workspaceId: string, courseId: string): Promise<CourseDetail> {
  return request<CourseDetail>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}`);
}

export async function fetchCourseJob(workspaceId: string, jobId: string): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs/${jobId}`);
}

export async function fetchCourseJobs(workspaceId: string): Promise<CourseGenerationJob[]> {
  return request<CourseGenerationJob[]>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs`);
}

export async function retryCourseJob(workspaceId: string, jobId: string): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs/${jobId}/retry`, { method: "POST" });
}

export async function cancelCourseJob(workspaceId: string, jobId: string): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/course-generation-jobs/${jobId}/cancel`, { method: "POST" });
}

export async function generateLesson(workspaceId: string, courseId: string, versionId: string, lessonId: string, outputLanguage: "zh-CN" | "en"): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/versions/${versionId}/lessons/${lessonId}/generations`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ external_processing_ack: true, output_language: outputLanguage }) });
}

export async function publishLesson(workspaceId: string, lessonId: string, versionId: string, expectedCurrentVersionId: string | null): Promise<LessonVersion> {
  return request<LessonVersion>(`/api/v1/workspaces/${workspaceId}/lessons/${lessonId}/versions/${versionId}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_current_published_version_id: expectedCurrentVersionId }) });
}

export async function activateCourse(workspaceId: string, courseId: string, versionId: string, expectedCurrentVersionId: string | null): Promise<CourseVersion> {
  return request<CourseVersion>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/versions/${versionId}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_current_active_version_id: expectedCurrentVersionId }) });
}

export async function fetchCourseReader(workspaceId: string, courseId: string): Promise<CourseReader> {
  return request<CourseReader>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/reader`);
}

export async function fetchLessonCompletions(workspaceId: string, courseId: string): Promise<LessonCompletion[]> {
  return request<LessonCompletion[]>(`/api/v1/workspaces/${workspaceId}/lesson-completions?course_id=${encodeURIComponent(courseId)}`);
}

export async function fetchWorkspaceLessonCompletions(workspaceId: string): Promise<LessonCompletion[]> {
  return request<LessonCompletion[]>(`/api/v1/workspaces/${workspaceId}/lesson-completions`);
}

export async function completeLesson(workspaceId: string, lessonVersionId: string): Promise<LessonCompletion> {
  return request<LessonCompletion>(`/api/v1/workspaces/${workspaceId}/lesson-versions/${lessonVersionId}/completion`, { method: "PUT" });
}

export async function undoLessonCompletion(workspaceId: string, lessonVersionId: string): Promise<void> {
  await request<void>(`/api/v1/workspaces/${workspaceId}/lesson-versions/${lessonVersionId}/completion`, { method: "DELETE" });
}

export async function regenerateCourseOutline(workspaceId: string, courseId: string, documentIds: string[], outputLanguage: "zh-CN" | "en"): Promise<CourseGenerationJob> {
  return request<CourseGenerationJob>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/outline-generations`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ document_ids: documentIds, external_processing_ack: true, output_language: outputLanguage }) });
}

export async function deleteCourse(workspaceId: string, courseId: string): Promise<void> {
  await request<void>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}`, { method: "DELETE" });
}

export async function fetchTutorSessions(workspaceId: string, courseId: string, versionId: string): Promise<TutorSession[]> {
  return request<TutorSession[]>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/tutor-sessions?course_version_id=${encodeURIComponent(versionId)}`);
}

export async function fetchTutorSkill(workspaceId: string, signal?: AbortSignal): Promise<TutorSkillCapability> {
  return request<TutorSkillCapability>(`/api/v1/workspaces/${workspaceId}/tutor-skill`, { signal });
}

export async function createTutorSession(workspaceId: string, courseId: string, versionId: string, externalProcessingAck: boolean): Promise<TutorSession> {
  return request<TutorSession>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/tutor-sessions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ course_version_id: versionId, external_processing_ack: externalProcessingAck }) });
}

export async function fetchTutorSession(workspaceId: string, sessionId: string): Promise<TutorSession> {
  return request<TutorSession>(`/api/v1/workspaces/${workspaceId}/tutor-sessions/${sessionId}`);
}

export async function deleteTutorSession(workspaceId: string, sessionId: string): Promise<void> {
  return request<void>(`/api/v1/workspaces/${workspaceId}/tutor-sessions/${sessionId}`, { method: "DELETE" });
}

export async function createTutorTurn(workspaceId: string, sessionId: string, payload: { question: string; scope: "course" | "lesson"; section_id?: string; lesson_id?: string; lesson_version_id?: string; science_tool_authorized?: boolean; code_tool_authorized?: boolean; code_run_id?: string }, idempotencyKey: string = crypto.randomUUID()): Promise<TutorTurn> {
  return request<TutorTurn>(`/api/v1/workspaces/${workspaceId}/tutor-sessions/${sessionId}/turns`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(payload) });
}

export async function cancelTutorTurn(workspaceId: string, turnId: string): Promise<TutorTurn> {
  return request<TutorTurn>(`/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}/cancel`, { method: "POST" });
}

export async function deleteTutorTurn(workspaceId: string, turnId: string): Promise<void> {
  return request<void>(`/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}`, { method: "DELETE" });
}

export async function retryTutorTurn(workspaceId: string, turnId: string): Promise<TutorTurn> {
  return request<TutorTurn>(`/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}/retry`, { method: "POST" });
}

export function tutorTurnEventsUrl(workspaceId: string, turnId: string): string {
  return `${API_BASE_URL}/api/v1/workspaces/${workspaceId}/tutor-turns/${turnId}/events`;
}

export async function fetchAgentRuns(workspaceId: string, query: AgentRunQuery = {}, signal?: AbortSignal): Promise<AgentRunSummary[]> {
  const params = new URLSearchParams();
  if (query.course_id) params.set("course_id", query.course_id);
  if (query.role) params.set("role", query.role);
  if (query.status) params.set("status", query.status);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<AgentRunSummary[]>(`/api/v1/workspaces/${workspaceId}/agent-runs${suffix}`, { signal });
}

export async function fetchAgentRun(workspaceId: string, runId: string, signal?: AbortSignal): Promise<AgentRunDetail> {
  return request<AgentRunDetail>(`/api/v1/workspaces/${workspaceId}/agent-runs/${runId}`, { signal });
}

export type PracticeItemType = "single_choice" | "short_answer" | "coding" | "scientific";
export type PracticeDifficulty = "easy" | "standard" | "hard";

export interface PracticeCitation { citation_key: string; document_name: string; heading_path: string[]; page_start: number | null; page_end: number | null; available: boolean }
export interface PracticeOptionRead { option_key: string; text: string }
export interface PracticeItemRead { id: string; ordinal: number; item_type: PracticeItemType; stem: string; options: PracticeOptionRead[] | null; citations: PracticeCitation[]; interaction_spec?: { language?: "python" | "java" | "cpp"; starter_code?: string; input_description?: string; output_description?: string; constraints?: string[]; public_examples?: Array<{ input: string; expected_output: string; weight: number }>; contract?: string; runtime?: string; time_limit_seconds?: number; output_limit_bytes?: number; unit?: string | null; equivalence_rule?: string } | null }
export interface PracticeSetRead { id: string; workspace_id: string; course_id: string; lesson_id: string; lesson_version_id: string; output_language: "zh-CN" | "en"; difficulty: PracticeDifficulty; item_count: number; lifecycle_status: string; source_degraded: boolean; created_at: string; items: PracticeItemRead[] }
export interface PracticeSetListItem { id: string; lesson_version_id: string; output_language: "zh-CN" | "en"; difficulty: PracticeDifficulty; item_count: number; lifecycle_status: string; source_degraded: boolean; created_at: string; latest_job: PracticeJobRead | null }
export interface ScienceVerificationRead { used: boolean; status: "verified" | "failed" | "not_used"; tool: "Wolfram" | null; purpose: "reference_answer" | "learner_final_result"; checked_at: string | null }
export interface PracticeJobRead { id: string; job_type: "generate_set" | "grade_attempt"; practice_set_id: string | null; practice_attempt_id: string | null; status: string; attempt_count: number; error_code: string | null; error_message: string | null; created_at: string; updated_at: string; science_verification?: ScienceVerificationRead | null }
export interface PracticeFeedbackBlockRead { block_key: string; type: "explanation" | "improvement" | "reference" | "limitation"; text: string; citation_ids: string[]; option_key: string | null }
export interface PracticeCriterionResultRead { criterion_key: string; met: "full" | "partial" | "none"; note: string }
export interface PracticeFeedbackRead { verdict: "correct" | "partially_correct" | "incorrect" | "ungradable"; score: number | null; is_ai_graded: boolean; criterion_results: PracticeCriterionResultRead[]; feedback_blocks: PracticeFeedbackBlockRead[]; citations: PracticeCitation[]; coding_tests_passed?: number | null; coding_tests_total?: number | null; coding_error_categories?: string[] | null; coding_public_cases?: Array<{ test_index: number; passed: boolean }> | null; science_verification?: ScienceVerificationRead | null }
export interface PracticeAttemptRead { id: string; practice_item_id: string; ordinal: number; item_type: PracticeItemType; status: string; option_key: string | null; text: string | null; source_code?: string | null; practice_job_id: string | null; error_code: string | null; error_message: string | null; created_at: string; completed_at: string | null; feedback: PracticeFeedbackRead | null }

export async function fetchPracticeSets(workspaceId: string, courseId: string, courseVersionId: string, lessonId: string, lessonVersionId: string): Promise<PracticeSetListItem[]> {
  return request<PracticeSetListItem[]>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/versions/${courseVersionId}/lessons/${lessonId}/versions/${lessonVersionId}/practice-sets`);
}

export async function createPracticeSet(workspaceId: string, courseId: string, courseVersionId: string, lessonId: string, lessonVersionId: string, payload: { item_count: number; difficulty: PracticeDifficulty; output_language?: "zh-CN" | "en"; item_type_mode?: "auto" | "general_only" | "require_coding" | "require_science"; code_languages?: string[] | null; code_tool_authorized?: boolean; science_tool_authorized?: boolean }, idempotencyKey: string = crypto.randomUUID()): Promise<PracticeJobRead> {
  return request<PracticeJobRead>(`/api/v1/workspaces/${workspaceId}/courses/${courseId}/versions/${courseVersionId}/lessons/${lessonId}/versions/${lessonVersionId}/practice-sets`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ ...payload, external_processing_ack: true }) });
}

export async function fetchPracticeSet(workspaceId: string, setId: string): Promise<PracticeSetRead> {
  return request<PracticeSetRead>(`/api/v1/workspaces/${workspaceId}/practice-sets/${setId}`);
}

export async function deletePracticeSet(workspaceId: string, setId: string): Promise<void> {
  await request<void>(`/api/v1/workspaces/${workspaceId}/practice-sets/${setId}`, { method: "DELETE" });
}

export async function fetchPracticeJob(workspaceId: string, jobId: string): Promise<PracticeJobRead> {
  return request<PracticeJobRead>(`/api/v1/workspaces/${workspaceId}/practice-jobs/${jobId}`);
}

export async function cancelPracticeJob(workspaceId: string, jobId: string): Promise<PracticeJobRead> {
  return request<PracticeJobRead>(`/api/v1/workspaces/${workspaceId}/practice-jobs/${jobId}/cancel`, { method: "POST" });
}

export async function retryPracticeJob(workspaceId: string, jobId: string): Promise<PracticeJobRead> {
  return request<PracticeJobRead>(`/api/v1/workspaces/${workspaceId}/practice-jobs/${jobId}/retry`, { method: "POST" });
}

export async function submitPracticeAttempt(workspaceId: string, itemId: string, payload: { external_processing_ack: boolean; option_key?: string; text?: string; source_code?: string; science_tool_authorized?: boolean }, idempotencyKey: string = crypto.randomUUID()): Promise<PracticeAttemptRead> {
  return request<PracticeAttemptRead>(`/api/v1/workspaces/${workspaceId}/practice-items/${itemId}/attempts`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(payload) });
}

export async function fetchPracticeAttempts(workspaceId: string, itemId: string): Promise<PracticeAttemptRead[]> {
  return request<PracticeAttemptRead[]>(`/api/v1/workspaces/${workspaceId}/practice-items/${itemId}/attempts`);
}

export async function fetchPracticeAttempt(workspaceId: string, attemptId: string): Promise<PracticeAttemptRead> {
  return request<PracticeAttemptRead>(`/api/v1/workspaces/${workspaceId}/practice-attempts/${attemptId}`);
}

export async function deletePracticeAttempt(workspaceId: string, attemptId: string): Promise<void> {
  await request<void>(`/api/v1/workspaces/${workspaceId}/practice-attempts/${attemptId}`, { method: "DELETE" });
}

// Stage 4 Slice 2: Learning API types and functions
export type MasteryBand = "insufficient" | "needs_review" | "developing" | "secure";
export interface MasteryTargetRead {
  target_id: string; target_title: string; target_key: string; band: MasteryBand;
  evidence_count: number; distinct_set_count: number; deterministic_signal_count: number;
  ai_signal_count: number; last_evidence_at: string | null; weakness_status: string | null;
  review_status: string | null; course_id: string; lesson_id: string; source_degraded: boolean;
}
export interface LearningStateRead {
  workspace_id: string; summary: Record<string, number>; targets: MasteryTargetRead[];
}
export interface ReviewItemRead {
  id: string; target_id: string; target_key: string; target_title: string; weakness_status: string; status: string;
  due_at: string | null; reopen_count: number; reason_snapshot: Record<string, unknown>;
  course_id: string; lesson_id: string; lesson_title: string; source_attempt_id: string | null; source_set_id: string | null;
  source_item_ordinal: number | null; source_is_ai: boolean | null; source_occurred_at: string | null; created_at: string; updated_at: string;
}
export interface LearningMemoryRead {
  id: string; target_title: string; target_key: string; kind: string; status: string;
  display_text: string; confirmed_at: string | null; last_supported_at: string | null;
  source_count: number; course_id: string; lesson_id: string; lesson_title: string;
  sources: { attempt_id: string; set_id: string; item_number: number; is_ai: boolean; occurred_at: string }[];
}
export interface LearningMemoryPolicyRead {
  tutor_use_enabled: boolean; policy_revision: number; updated_at: string;
}
export interface LearningJobRead {
  id: string; workspace_id: string; status: string; attempt_count: number;
  error_code: string | null; error_message: string | null;
  created_at: string; updated_at: string; completed_at: string | null;
}

export async function fetchLearningState(workspaceId: string, courseId?: string, lessonId?: string): Promise<LearningStateRead> {
  const params = new URLSearchParams();
  if (courseId) params.set("course_id", courseId);
  if (lessonId) params.set("lesson_id", lessonId);
  const q = params.size ? `?${params.toString()}` : "";
  return request<LearningStateRead>(`/api/v1/workspaces/${workspaceId}/learning-state${q}`);
}
export async function fetchReviewItems(workspaceId: string, status?: string, signal?: AbortSignal): Promise<ReviewItemRead[]> {
  const q = status ? `?status=${status}` : "";
  return request<ReviewItemRead[]>(`/api/v1/workspaces/${workspaceId}/review-items${q}`, { signal });
}
export async function createReviewAction(workspaceId: string, reviewItemId: string, action: string, snoozeDays?: number): Promise<unknown> {
  return request(`/api/v1/workspaces/${workspaceId}/review-items/${reviewItemId}/actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, snooze_days: snoozeDays }) });
}
export async function fetchLearningMemories(workspaceId: string): Promise<LearningMemoryRead[]> {
  return request<LearningMemoryRead[]>(`/api/v1/workspaces/${workspaceId}/learning-memories`);
}
export async function patchLearningMemory(workspaceId: string, memoryId: string, payload: { display_text?: string; action?: string }): Promise<unknown> {
  return request(`/api/v1/workspaces/${workspaceId}/learning-memories/${memoryId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}
export async function deleteLearningMemory(workspaceId: string, memoryId: string): Promise<void> {
  await request<void>(`/api/v1/workspaces/${workspaceId}/learning-memories/${memoryId}`, { method: "DELETE" });
}
export async function fetchMemoryPolicy(workspaceId: string): Promise<LearningMemoryPolicyRead> {
  return request<LearningMemoryPolicyRead>(`/api/v1/workspaces/${workspaceId}/learning-memory-policy`);
}
export async function patchMemoryPolicy(workspaceId: string, enabled: boolean): Promise<LearningMemoryPolicyRead> {
  return request<LearningMemoryPolicyRead>(`/api/v1/workspaces/${workspaceId}/learning-memory-policy`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tutor_use_enabled: enabled }) });
}
export async function createRecomputeJob(workspaceId: string): Promise<LearningJobRead> {
  return request<LearningJobRead>(`/api/v1/workspaces/${workspaceId}/learning-state/recompute`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}
export async function fetchLearningJob(workspaceId: string, jobId: string): Promise<LearningJobRead> {
  return request<LearningJobRead>(`/api/v1/workspaces/${workspaceId}/learning-jobs/${jobId}`);
}
export async function cancelLearningJob(workspaceId: string, jobId: string): Promise<LearningJobRead> {
  return request<LearningJobRead>(`/api/v1/workspaces/${workspaceId}/learning-jobs/${jobId}/cancel`, { method: "POST" });
}
export async function retryLearningJob(workspaceId: string, jobId: string): Promise<LearningJobRead> {
  return request<LearningJobRead>(`/api/v1/workspaces/${workspaceId}/learning-jobs/${jobId}/retry`, { method: "POST" });
}

interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
        message = body.detail[0].msg;
      }
    } catch {
      // Keep the status-based message for non-JSON errors.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Slice 4: MCP Capabilities & Code Lab
// ---------------------------------------------------------------------------

export interface McpCapability {
  capability: string;
  status: "ready" | "unavailable" | "degraded";
  detail: string;
}

export interface McpPolicy {
  workspace_id: string;
  code_execution_enabled: boolean;
  revision: number;
}

export interface CodeRunCreate {
  language: "python" | "java" | "cpp";
  source_code: string;
  stdin?: string;
  course_id?: string | null;
  course_version_id?: string | null;
  lesson_id?: string | null;
  lesson_version_id?: string | null;
}

export interface CodeRun {
  id: string;
  workspace_id: string;
  language: string;
  status: string;
  course_id: string | null;
  lesson_id: string | null;
  exit_code: number | null;
  duration_ms: number | null;
  runtime: string | null;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  created_at: string;
  completed_at: string | null;
  deleted_at: string | null;
}

export interface CodeRunDetail extends CodeRun {
  source_code: string;
  stdin: string;
  compile_output: string;
  stdout: string;
  stderr: string;
}

export async function listMcpCapabilities(
  workspaceId: string,
): Promise<McpCapability[]> {
  return request(`/api/v1/workspaces/${workspaceId}/mcp-capabilities`);
}

export async function getMcpPolicy(workspaceId: string): Promise<McpPolicy> {
  return request(`/api/v1/workspaces/${workspaceId}/mcp-policy`);
}

export async function patchMcpPolicy(
  workspaceId: string,
  patch: { code_execution_enabled: boolean },
): Promise<McpPolicy> {
  return request(`/api/v1/workspaces/${workspaceId}/mcp-policy`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function createCodeRun(
  workspaceId: string,
  body: CodeRunCreate,
  idempotencyKey: string,
): Promise<CodeRun> {
  return request(`/api/v1/workspaces/${workspaceId}/code-runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
}

export async function listCodeRuns(
  workspaceId: string,
  limit = 20,
  offset = 0,
): Promise<CodeRun[]> {
  return request(
    `/api/v1/workspaces/${workspaceId}/code-runs?limit=${limit}&offset=${offset}`,
  );
}

export async function getCodeRun(
  workspaceId: string,
  runId: string,
): Promise<CodeRunDetail> {
  return request(`/api/v1/workspaces/${workspaceId}/code-runs/${runId}`);
}

export async function cancelCodeRun(
  workspaceId: string,
  runId: string,
): Promise<CodeRun> {
  return request(
    `/api/v1/workspaces/${workspaceId}/code-runs/${runId}/cancel`,
    { method: "POST" },
  );
}

export async function deleteCodeRun(
  workspaceId: string,
  runId: string,
): Promise<void> {
  return request(`/api/v1/workspaces/${workspaceId}/code-runs/${runId}`, {
    method: "DELETE",
  });
}
