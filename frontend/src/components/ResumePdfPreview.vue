<template>
  <div class="pdf-preview">
    <div class="pdf-preview__toolbar">
      <div>
        <p class="pdf-preview__label">PDF preview</p>
        <p class="pdf-preview__meta">
          {{ toolbarMessage }}
        </p>
      </div>
      <a
        v-if="rawPdfUrl"
        :href="rawPdfUrl"
        target="_blank"
        rel="noreferrer"
        class="pdf-preview__link"
      >
        Open raw PDF
      </a>
    </div>

    <div v-if="warning" class="pdf-preview__warning">
      {{ warning }}
    </div>

    <div class="pdf-preview__body">
      <div v-if="!src" class="pdf-state">{{ emptyMessage }}</div>
      <div v-else class="pdf-embed-shell">
        <div v-if="showLoading" class="pdf-state pdf-state--overlay">Loading PDF...</div>
        <div v-if="showFallback" class="pdf-state pdf-state--overlay pdf-state--overlay-stack">
          <p class="pdf-state__message">
            Embedded preview is taking longer than expected. You can still open the live PDF in a new tab.
          </p>
          <a
            v-if="rawPdfUrl"
            :href="rawPdfUrl"
            target="_blank"
            rel="noreferrer"
            class="pdf-preview__link"
          >
            Open raw PDF
          </a>
        </div>
        <iframe
          ref="frameRef"
          class="pdf-frame"
          :src="viewerSrc"
          title="Resume PDF preview"
          @load="handleFrameLoad"
        ></iframe>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{
  src: string;
  compileStatus: string;
  warning?: string;
  lastCompiledAt?: string | null;
  rawPdfUrl?: string;
  emptyMessage?: string;
}>();

const frameRef = ref<HTMLIFrameElement | null>(null);
const showLoading = ref(false);
const showFallback = ref(false);
let loadingTimer: number | null = null;
let fallbackTimer: number | null = null;

const toolbarMessage = computed(() => {
  const compiledAt = props.lastCompiledAt ? new Date(props.lastCompiledAt).toLocaleString() : "Not yet";
  return `Status: ${props.compileStatus}. Last compile: ${compiledAt}.`;
});
const viewerSrc = computed(() => (props.src ? `${props.src}#view=FitH` : ""));

watch(
  () => props.src,
  (value) => {
    clearTimers();
    if (!value) {
      showLoading.value = false;
      showFallback.value = false;
      return;
    }
    showLoading.value = true;
    showFallback.value = false;
    loadingTimer = window.setTimeout(() => {
      showLoading.value = false;
      loadingTimer = null;
    }, 1200);
    fallbackTimer = window.setTimeout(() => {
      showFallback.value = true;
      fallbackTimer = null;
    }, 3200);
  },
  { immediate: true }
);

onBeforeUnmount(() => {
  clearTimers();
});

function handleFrameLoad() {
  showLoading.value = false;
  showFallback.value = false;
  clearTimers();
}

function clearTimers() {
  if (loadingTimer !== null) {
    window.clearTimeout(loadingTimer);
    loadingTimer = null;
  }
  if (fallbackTimer !== null) {
    window.clearTimeout(fallbackTimer);
    fallbackTimer = null;
  }
}
</script>

<style scoped>
.pdf-preview {
  min-height: 640px;
  height: auto;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color);
  border-radius: 18px;
  background: rgba(251, 248, 242, 0.98);
  overflow: hidden;
}

.pdf-preview__toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px 14px;
  border-bottom: 1px solid rgba(31, 36, 31, 0.08);
  background: rgba(255, 255, 255, 0.84);
}

.pdf-preview__label {
  margin: 0 0 4px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--accent);
}

.pdf-preview__meta {
  margin: 0;
  color: var(--ink-soft);
  line-height: 1.5;
}

.pdf-preview__link {
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  color: var(--accent);
}

.pdf-preview__warning {
  padding: 10px 18px;
  border-bottom: 1px solid rgba(189, 94, 44, 0.16);
  background: rgba(189, 94, 44, 0.08);
  color: #7d3e19;
}

.pdf-preview__body {
  position: relative;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.pdf-embed-shell {
  position: relative;
  height: 100%;
  min-height: 640px;
  background: #cfc5b2;
}

.pdf-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 640px;
  border: 0;
  background: white;
}

.pdf-state {
  padding: 40px 24px;
  color: var(--ink-soft);
}

.pdf-state--overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(251, 248, 242, 0.88);
  z-index: 1;
}

.pdf-state--overlay-stack {
  gap: 12px;
  flex-direction: column;
  text-align: center;
}

.pdf-state__message {
  margin: 0;
  max-width: 360px;
  line-height: 1.6;
}
</style>
