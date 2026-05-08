<template>
  <div class="jd-picker">
    <span class="jd-picker__label">Current JD</span>
    <el-select
      :model-value="selectedJdId"
      placeholder="Select JD"
      :loading="setCurrentPending"
      :disabled="!jds?.length"
      style="min-width: 240px"
      @change="handleChange"
    >
      <el-option
        v-for="item in jds ?? []"
        :key="item.jd_id"
        :label="optionLabel(item)"
        :value="item.jd_id"
      />
    </el-select>
  </div>
</template>

<script setup lang="ts">
import type { JDRecordResponse } from "../types/api";
import { useCurrentJdSelection } from "../composables/useCurrentJdSelection";

const { jds, selectedJdId, selectCurrentJd, setCurrentPending } = useCurrentJdSelection();

function optionLabel(item: JDRecordResponse): string {
  if (item.company && item.role) {
    return `${item.company} · ${item.role}`;
  }
  return item.role || item.company || item.jd_id;
}

function handleChange(value: string) {
  selectCurrentJd(value);
}
</script>

<style scoped>
.jd-picker {
  display: grid;
  gap: 6px;
}

.jd-picker__label {
  font-size: 12px;
  color: var(--ink-soft);
}
</style>
