<template>
  <AppShell title="Mock Interview">
    <template #header-actions>
      <div class="cta-row">
        <CurrentJdPicker />
        <el-button type="primary" :loading="createPending" @click="startMock">Start</el-button>
        <el-button :disabled="!session" :loading="submitPending" @click="submitAnswers">Submit</el-button>
        <el-button :disabled="!session || !hasScores" :loading="completePending" @click="completeMock">Report</el-button>
      </div>
    </template>

    <section class="panel section-stack">
      <div>
        <p class="eyebrow">Session setup</p>
        <h3 class="section-title">20-question targeted mock</h3>
      </div>
      <div class="mock-config">
        <el-radio-group v-model="mode">
          <el-radio-button label="weakness_global">Global weakness</el-radio-button>
          <el-radio-button label="weakness_dimension">Knowledge block</el-radio-button>
          <el-radio-button label="jd">Current JD</el-radio-button>
        </el-radio-group>
        <el-select
          v-if="mode === 'weakness_dimension'"
          v-model="targetDimension"
          placeholder="Dimension"
          class="dimension-select"
        >
          <el-option v-for="item in dimensions" :key="item" :label="item" :value="item" />
        </el-select>
        <span v-if="mode === 'jd'" class="chip">{{ currentJdLabel }}</span>
      </div>
      <div v-if="session" class="status-row">
        <el-tag>{{ session.status }}</el-tag>
        <span class="chip">{{ session.questions.length }}/{{ session.question_count }}</span>
        <span class="chip">answered {{ answeredCount }}</span>
        <span class="chip" v-for="item in sourceMixEntries" :key="item[0]">
          {{ item[0] }} {{ item[1] }}
        </span>
      </div>
    </section>

    <section v-if="session" class="mock-layout">
      <div class="question-list">
        <article v-for="question in session.questions" :key="question.mock_question_id" class="question-card">
          <div class="status-row">
            <span class="chip">#{{ question.position }}</span>
            <span class="chip">{{ question.dimension }}</span>
            <el-tag :type="sourceTagType(question.source_kind)">{{ question.source_kind }}</el-tag>
            <el-tag v-if="question.answer" :type="masteryTagType(question.answer.mastery_level)">
              {{ question.answer.mastery_level }}
            </el-tag>
          </div>
          <p class="question-prompt">{{ question.prompt }}</p>
          <div class="pill-row">
            <span class="chip" v-for="topic in question.topics" :key="`${question.mock_question_id}-${topic}`">
              {{ topic }}
            </span>
          </div>
          <el-input
            v-model="answers[question.mock_question_id]"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 8 }"
            placeholder="Your answer"
          />
          <div v-if="question.answer" class="score-strip">
            <span>accuracy {{ scoreLabel(question.answer.accuracy_score) }}</span>
            <span>structure {{ scoreLabel(question.answer.structure_score) }}</span>
            <span>depth {{ scoreLabel(question.answer.depth_score) }}</span>
          </div>
          <p v-if="question.answer?.score_summary" class="muted-copy prewrap">
            {{ question.answer.score_summary }}
          </p>
          <div v-if="question.answer?.gaps.length" class="pill-row">
            <span v-for="gap in question.answer.gaps" :key="`${question.mock_question_id}-${gap}`" class="chip">
              {{ gap }}
            </span>
          </div>
        </article>
      </div>

      <aside class="panel report-panel">
        <p class="eyebrow">Report</p>
        <h3 class="section-title">{{ session.status === "completed" ? "Completed" : "In progress" }}</h3>
        <p class="muted-copy prewrap">{{ session.summary || "Scores appear after submission." }}</p>
        <div class="report-metrics">
          <div>
            <span class="metric-value">{{ answeredCount }}</span>
            <span class="metric-label">answered</span>
          </div>
          <div>
            <span class="metric-value">{{ lowMasteryCount }}</span>
            <span class="metric-label">needs repair</span>
          </div>
        </div>
        <div class="section-stack">
          <article v-for="item in weakDimensionEntries" :key="item[0]" class="detail-card compact-card">
            <strong>{{ item[0] }}</strong>
            <span class="chip">{{ item[1] }}</span>
          </article>
        </div>
      </aside>
    </section>

    <section v-else class="panel">
      <p class="empty-state">No active mock session.</p>
    </section>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useMutation } from "@tanstack/vue-query";

import AppShell from "../components/AppShell.vue";
import CurrentJdPicker from "../components/CurrentJdPicker.vue";
import { useCurrentJdSelection } from "../composables/useCurrentJdSelection";
import { api } from "../lib/api";
import type { MockMode, MockSessionResponse, MockSourceKind } from "../types/api";

const dimensions = [
  "backend_basic",
  "system_design",
  "llm_foundations",
  "post_training_alignment",
  "llm_inference_serving",
  "rag_retrieval",
  "agent_orchestration",
  "llm_evaluation",
  "rag_llm",
  "algorithm",
  "behavioral",
  "english",
  "project_expression",
  "execution",
];

const mode = ref<MockMode>("weakness_global");
const targetDimension = ref("backend_basic");
const session = ref<MockSessionResponse | null>(null);
const answers = reactive<Record<string, string>>({});
const { selectedJdId, currentJdLabel } = useCurrentJdSelection();

const createMutation = useMutation({
  mutationFn: () =>
    api.createMockSession({
      mode: mode.value,
      jd_id: mode.value === "jd" ? selectedJdId.value || null : null,
      target_dimension: mode.value === "weakness_dimension" ? targetDimension.value : null,
      question_count: 20,
    }),
  onSuccess: (data) => {
    session.value = data;
    resetAnswers(data);
  },
  onError: showError,
});

const submitMutation = useMutation({
  mutationFn: () => {
    if (!session.value) throw new Error("No mock session.");
    return api.submitMockAnswers(session.value.session_id, {
      answers: session.value.questions.map((question) => ({
        mock_question_id: question.mock_question_id,
        user_answer: answers[question.mock_question_id]?.trim() || "",
      })),
    });
  },
  onSuccess: (data) => {
    session.value = data;
    resetAnswers(data);
  },
  onError: showError,
});

const completeMutation = useMutation({
  mutationFn: () => {
    if (!session.value) throw new Error("No mock session.");
    return api.completeMockSession(session.value.session_id);
  },
  onSuccess: (data) => {
    session.value = data;
    resetAnswers(data);
  },
  onError: showError,
});

const createPending = computed(() => createMutation.isPending.value);
const submitPending = computed(() => submitMutation.isPending.value);
const completePending = computed(() => completeMutation.isPending.value);
const hasScores = computed(() => Boolean(session.value?.questions.some((question) => question.answer)));
const answeredCount = computed(() =>
  session.value?.questions.filter((question) => answers[question.mock_question_id]?.trim()).length ?? 0
);
const lowMasteryCount = computed(() =>
  session.value?.questions.filter((question) => question.answer && question.answer.mastery_level !== "熟练掌握").length ?? 0
);
const sourceMixEntries = computed(() => Object.entries(session.value?.source_mix ?? {}));
const weakDimensionEntries = computed(() => {
  const counts = new Map<string, number>();
  for (const question of session.value?.questions ?? []) {
    if (!question.answer || question.answer.mastery_level === "熟练掌握") continue;
    counts.set(question.dimension, (counts.get(question.dimension) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
});

watch(session, (value) => {
  if (value) resetAnswers(value);
});

function startMock() {
  if (mode.value === "jd" && !selectedJdId.value) {
    ElMessage.warning("Select a JD first.");
    return;
  }
  createMutation.mutate();
}

function submitAnswers() {
  if (!session.value) return;
  if (answeredCount.value < session.value.questions.length) {
    ElMessage.warning("Answer all 20 questions before submitting.");
    return;
  }
  submitMutation.mutate();
}

function completeMock() {
  completeMutation.mutate();
}

function resetAnswers(data: MockSessionResponse) {
  for (const question of data.questions) {
    answers[question.mock_question_id] = question.answer?.user_answer ?? answers[question.mock_question_id] ?? "";
  }
}

function showError(error: unknown) {
  ElMessage.error(error instanceof Error ? error.message : "Request failed.");
}

function sourceTagType(sourceKind: MockSourceKind) {
  if (sourceKind === "original") return "success";
  if (sourceKind === "variant") return "warning";
  return "info";
}

function masteryTagType(level: string) {
  if (level === "熟练掌握") return "success";
  if (level === "需要加强") return "danger";
  return "warning";
}

function scoreLabel(value: number | null) {
  return typeof value === "number" ? `${value}/5` : "n/a";
}
</script>

<style scoped>
.mock-config {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.dimension-select {
  max-width: 260px;
}

.mock-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 20px;
  align-items: start;
}

.question-list {
  display: grid;
  gap: 16px;
}

.question-card {
  display: grid;
  gap: 14px;
  border-radius: 20px;
  padding: 18px;
  border: 1px solid var(--line);
  background: var(--surface-strong);
  box-shadow: var(--shadow);
}

.question-prompt {
  margin: 0;
  line-height: 1.7;
  font-weight: 650;
}

.score-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  color: var(--ink-soft);
  font-size: 13px;
  font-weight: 700;
}

.report-panel {
  position: sticky;
  top: 24px;
}

.report-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0;
}

.report-metrics > div {
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px;
  background: rgba(255, 255, 255, 0.55);
}

.metric-value,
.metric-label {
  display: block;
}

.metric-value {
  font-size: 28px;
  font-weight: 750;
}

.metric-label {
  margin-top: 4px;
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 700;
}

.compact-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 12px;
}

@media (max-width: 1080px) {
  .mock-layout {
    grid-template-columns: 1fr;
  }

  .report-panel {
    position: static;
  }
}

@media (max-width: 680px) {
  .score-strip {
    grid-template-columns: 1fr;
  }
}
</style>
