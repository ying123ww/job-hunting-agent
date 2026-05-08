import { computed, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";

import { api } from "../lib/api";
import { useWorkbenchStore } from "../stores/workbench";

export function useCurrentJdSelection() {
  const store = useWorkbenchStore();
  const queryClient = useQueryClient();

  const { data: jds } = useQuery({
    queryKey: ["jds"],
    queryFn: () => api.getJDs(),
  });

  watch(
    () => jds.value,
    (records) => {
      if (!records?.length) {
        if (store.selectedJdId) {
          store.setSelectedJdId("");
        }
        return;
      }
      if (records.some((item) => item.jd_id === store.selectedJdId)) {
        return;
      }
      const current = records.find((item) => item.is_current);
      store.setSelectedJdId(current?.jd_id || records[0]?.jd_id || "");
    },
    { immediate: true }
  );

  const currentJd = computed(
    () => jds.value?.find((item) => item.jd_id === store.selectedJdId)
      || jds.value?.find((item) => item.is_current)
      || null
  );

  const currentJdLabel = computed(() => {
    const item = currentJd.value;
    if (!item) {
      return "No current JD";
    }
    if (item.company && item.role) {
      return `${item.company} · ${item.role}`;
    }
    return item.role || item.company || item.jd_id;
  });

  const setCurrentMutation = useMutation({
    mutationFn: (jdId: string) => api.setCurrentJD(jdId),
    onSuccess: async (data) => {
      store.setSelectedJdId(data.current_jd_id || "");
      await queryClient.invalidateQueries({ queryKey: ["jds"] });
      await queryClient.invalidateQueries({ queryKey: ["overview"] });
      await queryClient.invalidateQueries({ queryKey: ["diagnosis"] });
      await queryClient.invalidateQueries({ queryKey: ["plan"] });
    },
  });

  function selectCurrentJd(jdId: string) {
    if (!jdId || jdId === store.selectedJdId) {
      return;
    }
    setCurrentMutation.mutate(jdId);
  }

  return {
    currentJd,
    currentJdLabel,
    jds,
    selectedJdId: computed(() => store.selectedJdId),
    selectCurrentJd,
    setCurrentPending: computed(() => setCurrentMutation.isPending.value),
  };
}
