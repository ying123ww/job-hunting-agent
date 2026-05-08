<template>
  <AppShell title="Plan">
    <template #header-actions>
      <div class="cta-row">
        <CurrentJdPicker />
        <el-input-number v-model="gapLimit" :min="1" :max="10" />
        <el-button type="primary" :loading="generatePending" @click="generatePlan">
          Generate today plan
        </el-button>
        <el-button :loading="syncPending" @click="syncPlan">Sync TickTick</el-button>
      </div>
    </template>

    <section class="panel section-stack">
      <div>
        <p class="eyebrow">Execution</p>
        <h3 class="section-title">Today’s active tasks</h3>
      </div>
      <p class="muted-copy">Current JD: {{ currentJdLabel }}</p>
      <p class="muted-copy">{{ plan?.summary ?? "No plan for today." }}</p>
      <p class="desktop-note" v-if="lastSyncMode">
        Last sync mode in this session: <strong>{{ lastSyncMode }}</strong>
      </p>
      <div class="task-list">
        <article class="task-card" v-for="task in plan?.tasks ?? []" :key="task.task_id">
          <div class="status-row">
            <span class="chip">{{ task.dimension }}</span>
            <span class="chip">priority {{ task.priority }}</span>
            <span class="chip">{{ task.duration_min }} min</span>
            <span class="chip">{{ task.status }}</span>
          </div>
          <h4>{{ task.title }}</h4>
          <p class="muted-copy">{{ task.reason }}</p>
          <p class="muted-copy">Due {{ new Date(task.due_at).toLocaleTimeString() }}</p>
        </article>
      </div>
      <p v-if="!plan?.tasks?.length" class="empty-state">
        No plan generated yet. Run a diagnosis first, then generate today’s plan.
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

const gapLimit = ref(3);
const lastSyncMode = ref<"dry_run" | "live" | "">("");
const queryClient = useQueryClient();
const store = useWorkbenchStore();
const { currentJdLabel } = useCurrentJdSelection();

const { data: plan } = useQuery({
  queryKey: computed(() => ["plan", "today", store.selectedJdId]),
  queryFn: () => api.getTodayPlan(store.selectedJdId || undefined),
});

const generateMutation = useMutation({
  mutationFn: () => api.generatePlan(gapLimit.value, store.selectedJdId || undefined),
  onSuccess: async (data) => {
    queryClient.setQueryData(["plan", "today", store.selectedJdId], data);
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});
const generatePending = computed(() => generateMutation.isPending.value);

const syncMutation = useMutation({
  mutationFn: () => api.syncTickTick(plan.value?.plan_id || undefined),
  onSuccess: async (data) => {
    lastSyncMode.value = data.mode;
    await queryClient.invalidateQueries({ queryKey: ["plan", "today"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});
const syncPending = computed(() => syncMutation.isPending.value);

function generatePlan() {
  generateMutation.mutate();
}

function syncPlan() {
  syncMutation.mutate();
}
</script>
