import type {
  AgentTurnResponse,
  DocumentDetailResponse,
  DocumentSummaryResponse,
  GapAnalysisResponse,
  HealthResponse,
  IngestResponse,
  JDRecordResponse,
  JDIngestPayload,
  MockAnswersSubmitPayload,
  MockSessionCreatePayload,
  MockSessionResponse,
  PlanResponse,
  QuestionEvaluateResponse,
  QuestionBankDetailResponse,
  QuestionIngestPayload,
  QuestionIngestResponse,
  ResumeCompileResponse,
  ResumeIngestPayload,
  ResumeSourceResponse,
  ResumeSourceUpdatePayload,
  ResumeTailorDraftResponse,
  SyncTickTickResponse,
  WorkspaceOverviewResponse,
} from "../types/api";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    throw new Error(await extractErrorDetail(response));
  }

  return (await response.json()) as T;
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    throw new Error(await extractErrorDetail(response));
  }

  return response.text();
}

async function extractErrorDetail(response: Response): Promise<string> {
  const raw = await response.text();
  if (!raw) {
    return `Request failed with status ${response.status}`;
  }
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
  } catch {
    // Fall through to raw text.
  }
  return raw;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  getOverview: (jdId?: string) => {
    const query = new URLSearchParams();
    if (jdId) {
      query.set("jd_id", jdId);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<WorkspaceOverviewResponse>(`/workspace/overview${suffix}`);
  },
  getResumeSource: () => request<ResumeSourceResponse>("/resume/source"),
  saveResumeSource: (payload: ResumeSourceUpdatePayload) =>
    request<ResumeSourceResponse>("/resume/source", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  compileResume: () =>
    request<ResumeCompileResponse>("/resume/compile", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  getResumeCompileLog: () => requestText("/resume/compile-log"),
  getResumePdfUrl: () => `${API_BASE_URL}/resume/pdf`,
  getJDs: () => request<JDRecordResponse[]>("/jds"),
  setCurrentJD: (jdId: string) =>
    request<{ current_jd_id: string | null }>("/jds/current", {
      method: "PUT",
      body: JSON.stringify({ jd_id: jdId }),
    }),
  getResumeTailorDraft: (jdId?: string) =>
    request<ResumeTailorDraftResponse>("/resume/tailor-draft", {
      method: "POST",
      body: JSON.stringify({ jd_id: jdId || null }),
    }),
  getDocuments: (params: {
    source_type?: string;
    active_only?: boolean;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params.source_type) {
      query.set("source_type", params.source_type);
    }
    if (typeof params.active_only === "boolean") {
      query.set("active_only", String(params.active_only));
    }
    if (typeof params.limit === "number") {
      query.set("limit", String(params.limit));
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<DocumentSummaryResponse[]>(`/documents${suffix}`);
  },
  getDocumentDetail: (documentId: string) =>
    request<DocumentDetailResponse>(`/documents/${documentId}`),
  getQuestionBankDetail: (documentId: string) =>
    request<QuestionBankDetailResponse>(`/questions/banks/${documentId}`),
  ingestResume: (payload: ResumeIngestPayload) =>
    request<IngestResponse>("/ingest/resume", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ingestJD: (payload: JDIngestPayload) =>
    request<IngestResponse>("/ingest/jd", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ingestQuestions: (payload: QuestionIngestPayload) =>
    request<QuestionIngestResponse>("/ingest/questions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  evaluateQuestions: (documentId: string) =>
    request<QuestionEvaluateResponse>("/questions/evaluate", {
      method: "POST",
      body: JSON.stringify({ document_id: documentId }),
    }),
  currentDiagnosis: (jdId?: string) => {
    const query = new URLSearchParams();
    if (jdId) {
      query.set("jd_id", jdId);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<GapAnalysisResponse>(`/diagnosis/current${suffix}`);
  },
  analyzeGaps: (limit = 3, jdId?: string) =>
    request<GapAnalysisResponse>("/diagnosis/gap", {
      method: "POST",
      body: JSON.stringify({ limit, jd_id: jdId || null }),
    }),
  getTodayPlan: (jdId?: string) => {
    const query = new URLSearchParams();
    if (jdId) {
      query.set("jd_id", jdId);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<PlanResponse>(`/plan/today${suffix}`);
  },
  generatePlan: (gap_limit = 3, jdId?: string) =>
    request<PlanResponse>("/plan/generate", {
      method: "POST",
      body: JSON.stringify({ gap_limit, jd_id: jdId || null }),
    }),
  syncTickTick: (planId?: string) =>
    request<SyncTickTickResponse>("/plan/sync_ticktick", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId || null }),
    }),

  listMockSessions: () => request<MockSessionResponse[]>("/mock/sessions"),
  getMockSession: (sessionId: string) => request<MockSessionResponse>(`/mock/sessions/${sessionId}`),
  createMockSession: (payload: MockSessionCreatePayload) =>
    request<MockSessionResponse>("/mock/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  submitMockAnswers: (sessionId: string, payload: MockAnswersSubmitPayload) =>
    request<MockSessionResponse>(`/mock/sessions/${sessionId}/answers`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  completeMockSession: (sessionId: string) =>
    request<MockSessionResponse>(`/mock/sessions/${sessionId}/complete`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  agentTurn: (message: string, jdId?: string) =>
    request<AgentTurnResponse>("/agent/turn", {
      method: "POST",
      body: JSON.stringify({ message, jd_id: jdId || null }),
    }),
};

export async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}
