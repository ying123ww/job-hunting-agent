import { nextTick } from "vue";
import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useWorkbenchStore } from "../../src/stores/workbench";

describe("workbench ui prefs", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActivePinia(createPinia());
  });

  it("persists the resume pane ratio", async () => {
    const store = useWorkbenchStore();

    store.setResumePaneRatio(0.6);
    await nextTick();

    setActivePinia(createPinia());
    const nextStore = useWorkbenchStore();
    expect(nextStore.resumePaneRatio).toBe(0.6);
  });

  it("clamps the resume pane ratio", () => {
    const store = useWorkbenchStore();

    store.setResumePaneRatio(0.99);

    expect(store.resumePaneRatio).toBe(0.68);
  });

  it("persists compile log expansion", async () => {
    const store = useWorkbenchStore();

    store.setResumeCompileLogExpanded(true);
    await nextTick();

    setActivePinia(createPinia());
    const nextStore = useWorkbenchStore();
    expect(nextStore.resumeCompileLogExpanded).toBe(true);
  });
});
