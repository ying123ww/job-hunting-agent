<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div>
        <p class="eyebrow">Interview Copilot</p>
        <h1 class="brand-title">Workbench</h1>
        <p class="sidebar-copy">
          A web-first console for interview prep, gap diagnosis, and execution.
        </p>
      </div>

      <el-menu
        :default-active="route.path"
        class="nav-menu"
        router
        background-color="transparent"
        text-color="var(--ink-soft)"
        active-text-color="var(--ink)"
      >
        <el-menu-item index="/dashboard">Dashboard</el-menu-item>
        <el-menu-item index="/sources">Sources</el-menu-item>
        <el-menu-item index="/diagnosis">Diagnosis</el-menu-item>
        <el-menu-item index="/plan">Plan</el-menu-item>
        <el-menu-item index="/chat">Chat</el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <span class="chip">{{ shellLabel }}</span>
        <span class="chip">{{ versionLabel }}</span>
      </div>
    </aside>

    <main class="app-main">
      <header class="page-header">
        <div>
          <p class="eyebrow">Single-user local workspace</p>
          <h2>{{ title }}</h2>
        </div>
        <slot name="header-actions" />
      </header>

      <section class="page-body">
        <slot />
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const props = defineProps<{ title: string }>();
const route = useRoute();

const shellLabel = computed(() =>
  window.desktop?.isElectron ? "Electron shell" : "Browser app"
);
const versionLabel = computed(() =>
  window.desktop?.isElectron ? `v${window.desktop.getAppVersion()}` : "web"
);
</script>
