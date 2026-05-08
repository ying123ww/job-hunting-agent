<template>
  <AppShell title="Diagnosis">
    <template #header-actions>
      <div class="cta-row">
        <CurrentJdPicker />
        <el-input-number v-model="limit" :min="1" :max="10" />
        <el-button type="primary" :loading="analyzePending" @click="runDiagnosis">
          Run gap analysis
        </el-button>
      </div>
    </template>

    <section class="panel section-stack">
      <div>
        <p class="eyebrow">Current state</p>
        <h3 class="section-title">Latest weakness map and supporting evidence</h3>
      </div>
      <p class="muted-copy">Current JD: {{ currentJdLabel }}</p>
      <p class="muted-copy">
        Overall risk:
        <strong>{{ diagnosis?.overall_risk ?? "n/a" }}</strong>
      </p>
      <div class="gap-card" v-for="gap in diagnosis?.top_gaps ?? []" :key="gap.gap_id">
        <div class="status-row">
          <el-tag :type="severityType(gap.severity)">{{ gap.severity }}</el-tag>
          <span class="chip">{{ gap.dimension }}</span>
          <span class="chip">priority {{ gap.priority_score.toFixed(1) }}</span>
        </div>
        <p class="prewrap">{{ gap.why_it_matters }}</p>
        <div class="pill-row">
          <span class="chip" v-for="action in gap.repair_actions" :key="action">{{ action }}</span>
        </div>
        <div class="evidence-list">
          <article class="detail-card" v-for="item in gap.evidence" :key="item.chunk_id">
            <div class="status-row">
              <span class="chip">{{ item.source_type }}</span>
              <span class="chip">score {{ item.score.toFixed(2) }}</span>
            </div>
            <p class="prewrap">{{ item.text }}</p>
          </article>
        </div>
      </div>
      <p v-if="!diagnosis?.top_gaps?.length" class="empty-state">
        No diagnosis data yet. Upload question sets and run analysis.
      </p>
    </section>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";

import AppShell from "../components/AppShell.vue";
import CurrentJdPicker from "../components/CurrentJdPicker.vue";
import { useCurrentJdSelection } from "../composables/useCurrentJdSelection";
import { api } from "../lib/api";
import { useWorkbenchStore } from "../stores/workbench";

const queryClient = useQueryClient();
const limit = ref(3);
const store = useWorkbenchStore();
const { currentJdLabel } = useCurrentJdSelection();
const { data: diagnosis } = useQuery({
  queryKey: computed(() => ["diagnosis", "current", store.selectedJdId]),
  queryFn: () => api.currentDiagnosis(store.selectedJdId || undefined),
});

const analyzeMutation = useMutation({
  mutationFn: () => api.analyzeGaps(limit.value, store.selectedJdId || undefined),
  onSuccess: async (data) => {
    queryClient.setQueryData(["diagnosis", "current", store.selectedJdId], data);
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});
const analyzePending = computed(() => analyzeMutation.isPending.value);

function runDiagnosis() {
  analyzeMutation.mutate();
}

function severityType(severity: string) {
  if (severity === "high") return "danger";
  if (severity === "medium") return "warning";
  return "success";
}
</script>
