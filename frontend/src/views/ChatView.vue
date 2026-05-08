<template>
  <AppShell title="Chat">
    <template #header-actions>
      <div class="cta-row">
        <CurrentJdPicker />
        <el-button @click="store.resetChat" plain>Clear local transcript</el-button>
      </div>
    </template>

    <div class="split-layout">
      <section class="panel section-stack">
        <div>
          <p class="eyebrow">Conversation</p>
          <h3 class="section-title">Agent-backed prep chat</h3>
        </div>
        <p class="muted-copy">Current JD: {{ currentJdLabel }}</p>
        <div class="message-list">
          <article
            v-for="message in store.chatTranscript"
            :key="message.id"
            class="chat-card"
            :class="message.role === 'user' ? 'chat-card--user' : 'chat-card--assistant'"
          >
            <div class="message-meta">
              <span class="chip">{{ message.role }}</span>
              <span class="muted-copy">{{ new Date(message.timestamp).toLocaleString() }}</span>
            </div>
            <p class="prewrap">{{ message.content }}</p>
          </article>
        </div>
        <p v-if="!store.hasChatTranscript" class="empty-state">
          No local transcript yet. Your messages will stay in local browser storage on this machine.
        </p>

        <el-input
          v-model="draft"
          type="textarea"
          :rows="5"
          placeholder="Ask about your resume, target JD, weak points, or what to practice next."
        />
        <div class="form-actions">
          <el-button type="primary" :loading="turnPending" @click="sendMessage">
            Send
          </el-button>
        </div>
      </section>

      <section class="panel section-stack">
        <div>
          <p class="eyebrow">Evidence</p>
          <h3 class="section-title">Latest assistant citations</h3>
        </div>
        <div class="evidence-list" v-if="latestAssistantEvidence.length">
          <article class="detail-card" v-for="item in latestAssistantEvidence" :key="`${item.chunk_id}-${item.document_id}`">
            <div class="status-row">
              <span class="chip">{{ item.source_type }}</span>
              <span class="chip">score {{ item.score.toFixed(2) }}</span>
            </div>
            <p class="prewrap">{{ item.text }}</p>
          </article>
        </div>
        <p v-else class="empty-state">
          The agent has not cited evidence in this session yet.
        </p>
      </section>
    </div>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useMutation } from "@tanstack/vue-query";

import AppShell from "../components/AppShell.vue";
import CurrentJdPicker from "../components/CurrentJdPicker.vue";
import { useCurrentJdSelection } from "../composables/useCurrentJdSelection";
import { api } from "../lib/api";
import { useWorkbenchStore } from "../stores/workbench";

const store = useWorkbenchStore();
const { currentJdLabel } = useCurrentJdSelection();
const draft = ref("");

const turnMutation = useMutation({
  mutationFn: (message: string) => api.agentTurn(message, store.selectedJdId || undefined),
  onSuccess: (response, message) => {
    store.appendUserMessage(message);
    store.appendAssistantMessage(response);
    draft.value = "";
  },
});
const turnPending = computed(() => turnMutation.isPending.value);

const latestAssistantEvidence = computed(() => {
  const lastAssistant = [...store.chatTranscript]
    .reverse()
    .find((entry) => entry.role === "assistant" && entry.evidence?.length);
  return lastAssistant?.evidence || [];
});

function sendMessage() {
  if (!draft.value.trim()) return;
  turnMutation.mutate(draft.value.trim());
}
</script>
