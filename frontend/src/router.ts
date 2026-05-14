import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "./views/DashboardView.vue";
import SourcesView from "./views/SourcesView.vue";
import DiagnosisView from "./views/DiagnosisView.vue";
import PlanView from "./views/PlanView.vue";
import MockView from "./views/MockView.vue";
import ChatView from "./views/ChatView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    { path: "/dashboard", component: DashboardView },
    { path: "/sources", component: SourcesView },
    { path: "/diagnosis", component: DiagnosisView },
    { path: "/plan", component: PlanView },
    { path: "/mock", component: MockView },
    { path: "/chat", component: ChatView },
  ],
});
