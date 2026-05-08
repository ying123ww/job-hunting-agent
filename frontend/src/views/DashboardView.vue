<template>
  <AppShell title="Dashboard">
    <template #header-actions>
      <div class="cta-row">
        <el-button type="primary" @click="router.push('/sources')">Upload source</el-button>
        <el-button @click="router.push('/diagnosis')">Run diagnosis</el-button>
        <el-button @click="router.push('/plan')">Generate plan</el-button>
        <el-button @click="router.push('/chat')">Open chat</el-button>
      </div>
    </template>

    <div class="overview-grid" v-if="overview">
      <OverviewCard
        label="Active Sources"
        title="Resumes"
        :value="String(overview.active_document_counts.resume ?? 0)"
        description="Active resume documents in the current workspace."
      />
      <OverviewCard
        label="Active Sources"
        title="JDs"
        :value="String(overview.active_document_counts.jd ?? 0)"
        description="Tracked job descriptions for target roles."
      />
      <OverviewCard
        label="Diagnostics"
        title="Overall Risk"
        :value="overview.latest_overall_risk ?? 'n/a'"
        description="Latest saved risk snapshot from gap analysis."
      />
      <OverviewCard
        label="TickTick"
        title="Sync Mode"
        :value="overview.ticktick_sync_mode"
        description="Current task sync mode for this workspace."
      />
    </div>

    <div class="split-layout">
      <section class="panel section-stack">
        <div>
          <p class="eyebrow">Latest gaps</p>
          <h3 class="section-title">Where the workbench thinks you are leaking signal</h3>
        </div>
        <div class="gap-card" v-for="gap in overview?.top_gaps ?? []" :key="gap.gap_id">
          <div class="status-row">
            <el-tag class="severity-tag" :type="severityType(gap.severity)">{{ gap.severity }}</el-tag>
            <span class="chip">{{ gap.dimension }}</span>
            <span class="chip">priority {{ gap.priority_score.toFixed(1) }}</span>
          </div>
          <p class="prewrap">{{ gap.why_it_matters }}</p>
        </div>
        <p v-if="!overview?.top_gaps?.length" class="empty-state">
          No gap data yet. Upload resume/JD/questions, then run diagnosis.
        </p>
      </section>

      <section class="panel section-stack">
        <div>
          <p class="eyebrow">Today</p>
          <h3 class="section-title">Plan summary</h3>
        </div>
        <p class="muted-copy">{{ overview?.today_plan.summary ?? "No plan for today." }}</p>
        <div class="task-list">
          <article class="task-card" v-for="task in overview?.today_plan.tasks ?? []" :key="task.task_id">
            <div class="status-row">
              <span class="chip">{{ task.dimension }}</span>
              <span class="chip">{{ task.duration_min }} min</span>
              <span class="chip">{{ task.status }}</span>
            </div>
            <h4>{{ task.title }}</h4>
            <p class="muted-copy">{{ task.reason }}</p>
          </article>
        </div>
      </section>
    </div>
  </AppShell>
</template>

<script setup lang="ts">
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";

import AppShell from "../components/AppShell.vue";
import OverviewCard from "../components/OverviewCard.vue";
import { api } from "../lib/api";

const router = useRouter();
const { data: overview } = useQuery({
  queryKey: ["overview"],
  queryFn: () => api.getOverview(),
});

function severityType(severity: string) {
  if (severity === "high") return "danger";
  if (severity === "medium") return "warning";
  return "success";
}
</script>
