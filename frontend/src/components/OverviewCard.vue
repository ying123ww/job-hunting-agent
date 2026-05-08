<template>
  <article class="overview-card">
    <p class="eyebrow">{{ label }}</p>
    <h3>{{ title }}</h3>
    <p class="overview-card__value">{{ value }}</p>
    <p v-if="description" class="overview-card__description">{{ description }}</p>
  </article>
</template>

<script setup lang="ts">
defineProps<{
  label: string;
  title: string;
  value: string;
  description?: string;
}>();
</script>
