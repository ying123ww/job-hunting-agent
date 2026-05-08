export interface EvidenceResponse {
  source_type: string;
  document_id: string;
  chunk_id: string;
  text: string;
  score: number;
  metadata_summary: Record<string, unknown>;
}

export interface GapResponse {
  gap_id: string;
  dimension: string;
  severity: string;
  priority_score: number;
  why_it_matters: string;
  evidence: EvidenceResponse[];
  repair_actions: string[];
}

export interface TaskResponse {
  task_id: string;
  title: string;
  dimension: string;
  priority: number;
  due_at: string;
  duration_min: number;
  status: string;
  reason: string;
}

export interface PlanResponse {
  plan_id: string;
  jd_id: string | null;
  summary: string;
  tasks: TaskResponse[];
}

export interface HealthResponse {
  status: string;
  app_name: string;
}

export interface IngestResponse {
  document_id: string;
  chunk_count: number;
  content_hash: string;
  message: string;
}

export interface ResumeSourceResponse {
  source: string;
  last_saved_at: string | null;
  last_compiled_at: string | null;
  last_compile_status: string;
  last_compile_error_summary: string | null;
  last_resume_document_id: string | null;
  compiler_available: boolean;
  pdf_exists: boolean;
}

export interface ResumeCompileResponse {
  last_compiled_at: string;
  last_compile_status: string;
  last_compile_error_summary: string | null;
  compiler_available: boolean;
  pdf_exists: boolean;
  log_excerpt: string;
}

export interface QuestionRecordResponse {
  question_id: string;
  question: string;
  user_answer: string;
  reference_answer: string;
  dimension: string;
  topics: string[];
  mastery_level: string;
  gaps: string[];
  next_probe: string[];
}

export interface QuestionIngestResponse extends IngestResponse {
  processed_count: number;
  deduped_count: number;
  skipped_count: number;
  inactive_count: number;
  fallback_used: boolean;
  pipeline_version: string;
  top_gaps_found: string[];
  records: QuestionRecordResponse[];
}

export interface GapAnalysisResponse {
  overall_risk: string;
  generated_at: string;
  top_gaps: GapResponse[];
}

export interface SyncTickTickResponse {
  synced: number;
  mode: "dry_run" | "live";
  tasks: TaskResponse[];
}

export interface AgentTurnResponse {
  turn_id: string;
  intent: string;
  reply: string;
  current_jd_id: string | null;
  generated_plan_id: string | null;
  evidence: EvidenceResponse[];
  lifecycle: string[];
  memory_now: Record<string, string>;
}

export interface DocumentSummaryResponse {
  document_id: string;
  source_type: string;
  filename: string | null;
  content_hash: string;
  is_active: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface DocumentDetailResponse extends DocumentSummaryResponse {
  raw_text_preview: string;
}

export interface WorkspaceOverviewResponse {
  active_document_counts: Record<string, number>;
  latest_overall_risk: string | null;
  top_gaps: GapResponse[];
  today_plan: PlanResponse;
  ticktick_sync_mode: "dry_run" | "live";
}

export interface ResumeIngestPayload {
  user_id?: string;
  text?: string;
  content_base64?: string;
  filename?: string;
  metadata?: Record<string, unknown>;
}

export interface ResumeSourceUpdatePayload {
  user_id?: string;
  source: string;
}

export interface JDIngestPayload extends ResumeIngestPayload {
  company?: string;
  role?: string;
}

export interface QuestionIngestPayload extends ResumeIngestPayload {
  source_company?: string;
  source_role?: string;
}
