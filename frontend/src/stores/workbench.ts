import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";

import type { AgentTurnResponse, QuestionIngestResponse } from "../types/api";

export interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  evidence?: AgentTurnResponse["evidence"];
}

const CHAT_STORAGE_KEY = "interview-copilot.chat.v1";
const WORKBENCH_UI_STORAGE_KEY = "interview-copilot.workbench-ui.v1";

interface WorkbenchUIPrefs {
  resumePaneRatio?: number;
  resumeCompileLogExpanded?: boolean;
}

export const useWorkbenchStore = defineStore("workbench", () => {
  const uiPrefs = loadWorkbenchUIPrefs();
  const currentSourceTab = ref<"resume" | "jd" | "question">("resume");
  const selectedDocumentId = ref<string>("");
  const selectedJdId = ref<string>("");
  const resumeDraft = ref("");
  const resumePaneRatio = ref(clampResumePaneRatio(uiPrefs.resumePaneRatio ?? 0.42));
  const resumeCompileLogExpanded = ref(Boolean(uiPrefs.resumeCompileLogExpanded));
  const jdDraft = ref("");
  const questionDraft = ref("");
  const jdCompanyDraft = ref("");
  const jdRoleDraft = ref("");
  const questionCompanyDraft = ref("");
  const questionRoleDraft = ref("");
  const lastQuestionIngest = ref<QuestionIngestResponse | null>(null);
  const chatTranscript = ref<ChatEntry[]>(loadChatTranscript());

  watch(
    chatTranscript,
    (value) => {
      window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(value));
    },
    { deep: true }
  );

  watch(
    [resumePaneRatio, resumeCompileLogExpanded],
    ([paneRatio, compileLogExpanded]) => {
      const payload: WorkbenchUIPrefs = {
        resumePaneRatio: clampResumePaneRatio(paneRatio),
        resumeCompileLogExpanded: compileLogExpanded,
      };
      window.localStorage.setItem(WORKBENCH_UI_STORAGE_KEY, JSON.stringify(payload));
    },
    { deep: true }
  );

  const hasChatTranscript = computed(() => chatTranscript.value.length > 0);

  function setResumePaneRatio(value: number) {
    resumePaneRatio.value = clampResumePaneRatio(value);
  }

  function setResumeCompileLogExpanded(value: boolean) {
    resumeCompileLogExpanded.value = value;
  }

  function appendUserMessage(content: string) {
    chatTranscript.value.push({
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestamp: new Date().toISOString(),
    });
  }

  function appendAssistantMessage(response: AgentTurnResponse) {
    chatTranscript.value.push({
      id: response.turn_id,
      role: "assistant",
      content: response.reply,
      timestamp: new Date().toISOString(),
      evidence: response.evidence,
    });
    if (response.current_jd_id) {
      selectedJdId.value = response.current_jd_id;
    }
  }

  function resetChat() {
    chatTranscript.value = [];
  }

  return {
    chatTranscript,
    currentSourceTab,
    hasChatTranscript,
    jdCompanyDraft,
    jdDraft,
    jdRoleDraft,
    lastQuestionIngest,
    questionCompanyDraft,
    questionDraft,
    questionRoleDraft,
    resumeDraft,
    resumePaneRatio,
    resumeCompileLogExpanded,
    selectedDocumentId,
    selectedJdId,
    setResumeCompileLogExpanded,
    setResumePaneRatio,
    appendAssistantMessage,
    appendUserMessage,
    resetChat,
  };
});

function loadChatTranscript(): ChatEntry[] {
  const raw = window.localStorage.getItem(CHAT_STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function loadWorkbenchUIPrefs(): WorkbenchUIPrefs {
  const raw = window.localStorage.getItem(WORKBENCH_UI_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed as WorkbenchUIPrefs : {};
  } catch {
    return {};
  }
}

function clampResumePaneRatio(value: number): number {
  return Math.min(0.68, Math.max(0.32, value));
}
