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

export const useWorkbenchStore = defineStore("workbench", () => {
  const currentSourceTab = ref<"resume" | "jd" | "question">("resume");
  const selectedDocumentId = ref<string>("");
  const selectedJdId = ref<string>("");
  const resumeDraft = ref("");
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

  const hasChatTranscript = computed(() => chatTranscript.value.length > 0);

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
    selectedDocumentId,
    selectedJdId,
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
