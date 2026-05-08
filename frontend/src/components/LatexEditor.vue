<template>
  <div ref="host" class="latex-editor"></div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { EditorState } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { keymap, lineNumbers, EditorView } from "@codemirror/view";
import { StreamLanguage } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";

const props = defineProps<{
  modelValue: string;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: string): void;
}>();

const host = ref<HTMLElement | null>(null);
let view: EditorView | null = null;

onMounted(() => {
  if (!host.value) {
    return;
  }
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        lineNumbers(),
        history(),
        keymap.of([...defaultKeymap, ...historyKeymap]),
        EditorView.lineWrapping,
        StreamLanguage.define(stex),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            emit("update:modelValue", update.state.doc.toString());
          }
        }),
        EditorView.theme({
          "&": {
            height: "100%",
            fontSize: "14px",
          },
          ".cm-scroller": {
            overflow: "auto",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          },
          ".cm-content": {
            minHeight: "100%",
            padding: "16px 0",
          },
          ".cm-line": {
            padding: "0 16px",
          },
          ".cm-gutters": {
            borderRight: "1px solid var(--el-border-color)",
            background: "var(--el-fill-color-light)",
          },
          ".cm-activeLineGutter": {
            background: "transparent",
          },
        }),
      ],
    }),
  });
});

watch(
  () => props.modelValue,
  (value) => {
    if (!view) {
      return;
    }
    const current = view.state.doc.toString();
    if (value === current) {
      return;
    }
    view.dispatch({
      changes: {
        from: 0,
        to: current.length,
        insert: value,
      },
    });
  }
);

onBeforeUnmount(() => {
  view?.destroy();
  view = null;
});
</script>

<style scoped>
.latex-editor {
  min-height: 420px;
  height: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 16px;
  overflow: hidden;
  background: var(--el-bg-color);
}
</style>
