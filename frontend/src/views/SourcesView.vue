<template>
  <AppShell title="Sources">
    <template #header-actions>
      <CurrentJdPicker />
    </template>

    <template #sidebar-extra>
      <div class="sources-sidebar-block">
        <p class="eyebrow">Sources</p>
        <nav class="source-nav" aria-label="Source sections">
          <button
            v-for="item in sourceNavItems"
            :key="item.value"
            type="button"
            class="source-nav__button"
            :class="{ 'is-active': store.currentSourceTab === item.value }"
            @click="store.currentSourceTab = item.value"
          >
            <span class="source-nav__title">{{ item.label }}</span>
            <span class="source-nav__copy">{{ item.description }}</span>
          </button>
        </nav>

        <article v-if="store.currentSourceTab === 'resume'" class="detail-card sources-sidebar-status">
          <p class="eyebrow">Resume status</p>
          <div class="sources-sidebar-status__chips">
            <span class="chip">{{ resumeDirty ? "unsaved changes" : "saved" }}</span>
            <span class="chip">{{ resumeSourceData?.compiler_available ? "tectonic ready" : "tectonic missing" }}</span>
          </div>
          <p class="muted-copy sources-sidebar-status__meta">
            Current document: {{ resumeSourceData?.last_resume_document_id ?? "Not saved yet" }}
          </p>
          <p class="muted-copy sources-sidebar-status__meta">
            Current JD anchor: {{ currentJdLabel }}
          </p>
          <p class="muted-copy sources-sidebar-status__meta">
            Last compile: {{ formatTimestamp(resumeStatus.last_compiled_at) }}
          </p>
          <div class="sources-sidebar-status__actions">
            <el-button type="primary" :loading="resumeSavePending" @click="submitResumeSource">
              Save source
            </el-button>
            <el-button
              :loading="resumeCompilePending"
              :disabled="resumeDirty || !resumeSourceData?.compiler_available"
              @click="submitResumeCompile"
            >
              Compile PDF
            </el-button>
            <el-button :loading="resumeTailorPending" :disabled="!currentJd" @click="generateResumeTailorDraft">
              Generate JD draft
            </el-button>
          </div>
          <p class="muted-copy sources-sidebar-status__meta">
            Status: {{ resumeStatus.last_compile_status }}
          </p>
        </article>
      </div>
    </template>

    <section class="sources-stage">
      <div
        v-if="store.currentSourceTab === 'resume'"
        ref="resumeWorkspaceRef"
        class="resume-workspace"
      >
        <section class="panel resume-editor-pane" :style="resumeEditorPaneStyle">
          <div class="resume-pane__header">
            <div>
              <p class="eyebrow">Editor</p>
              <h3 class="section-title">resume.tex</h3>
            </div>
            <span class="chip">{{ editorPaneWidthLabel }}</span>
          </div>
          <div class="resume-pane__body">
            <LatexEditor v-model="store.resumeDraft" />
          </div>
        </section>

        <div
          v-if="!isNarrowViewport"
          class="resume-divider"
          :class="{ 'is-dragging': isDraggingDivider }"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize editor and PDF panes"
          @pointerdown="startResumePaneResize"
        >
          <span class="resume-divider__handle"></span>
        </div>

        <section class="panel resume-preview-pane" :style="resumePreviewPaneStyle">
          <ResumePdfPreview
            class="resume-preview-surface"
            :src="resumeStatus.pdf_exists ? resumePdfUrl : ''"
            :compile-status="resumeStatus.last_compile_status"
            :last-compiled-at="resumeStatus.last_compiled_at"
            :warning="resumePdfWarning"
            :raw-pdf-url="resumeStatus.pdf_exists ? resumePdfUrl : ''"
            :empty-message="resumePdfEmptyMessage"
          />

          <article v-if="resumeTailorDraft" class="detail-card resume-tailor-card">
            <div class="resume-log-card__header">
              <div>
                <p class="eyebrow">Tailor draft</p>
                <p class="muted-copy">{{ resumeTailorDraft.summary }}</p>
              </div>
              <span class="chip">{{ currentJdLabel }}</span>
            </div>
            <div class="pill-row" v-if="resumeTailorDraft.highlighted_keywords.length">
              <span class="chip" v-for="keyword in resumeTailorDraft.highlighted_keywords" :key="keyword">
                {{ keyword }}
              </span>
            </div>
            <ul class="tailor-list">
              <li v-for="suggestion in resumeTailorDraft.suggestions" :key="suggestion" class="muted-copy">
                {{ suggestion }}
              </li>
            </ul>
          </article>

          <article class="detail-card resume-log-card">
            <div class="resume-log-card__header">
              <div>
                <p class="eyebrow">Compile log</p>
                <p class="muted-copy">
                  {{ resumeStatus.last_compile_error_summary || "Latest compiler output." }}
                </p>
              </div>
              <el-button text @click="toggleResumeCompileLog">
                {{ store.resumeCompileLogExpanded ? "Hide log" : "Show log" }}
              </el-button>
            </div>
            <pre v-if="store.resumeCompileLogExpanded" class="raw-preview resume-log-card__body">{{ resumeCompileLog }}</pre>
          </article>
        </section>
      </div>

      <div
        v-else
        class="sources-stack-layout"
      >
        <section class="panel section-stack">
          <div>
            <p class="eyebrow">Ingestion</p>
            <h3 class="section-title">Upload or paste core prep materials</h3>
          </div>

          <template v-if="store.currentSourceTab === 'jd'">
            <div class="section-stack">
              <el-input v-model="store.jdCompanyDraft" placeholder="Company" />
              <el-input v-model="store.jdRoleDraft" placeholder="Role" />
              <el-input v-model="store.jdUrlDraft" placeholder="Posting URL" />
              <el-input
                v-model="store.jdDescriptionDraft"
                type="textarea"
                :rows="6"
                placeholder="Paste the position description."
              />
              <el-input
                v-model="store.jdRequirementsDraft"
                type="textarea"
                :rows="8"
                placeholder="Paste the position requirements."
              />
              <input type="file" @change="onJdFile" />
              <div class="form-actions">
                <el-button type="primary" :loading="jdPending" @click="submitJd">
                  Save JD
                </el-button>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="section-stack">
              <el-input v-model="store.questionCompanyDraft" placeholder="Source company (optional)" />
              <el-input v-model="store.questionRoleDraft" placeholder="Source role (optional)" />
              <el-input
                v-model="store.questionDraft"
                type="textarea"
                :rows="10"
                placeholder="Paste interview questions and your answers."
              />
              <input type="file" @change="onQuestionFile" />
              <div class="form-actions">
                <el-button type="primary" :loading="questionSubmitPending" @click="submitQuestions">
                  Save question set
                </el-button>
              </div>
              <article v-if="questionWorkflowStatus" class="detail-card question-workflow-card">
                <div class="question-workflow-card__header">
                  <div>
                    <p class="eyebrow">Workflow status</p>
                    <h4>{{ questionWorkflowStatus.title }}</h4>
                  </div>
                  <span class="chip">{{ questionWorkflowStatus.badge }}</span>
                </div>
                <p class="muted-copy prewrap">{{ questionWorkflowStatus.description }}</p>
              </article>
            </div>
          </template>
        </section>

        <section v-if="store.currentSourceTab === 'question'" class="panel section-stack">
          <div>
            <p class="eyebrow">Question bank</p>
            <h3 class="section-title">Saved sets with evaluation summaries</h3>
          </div>
          <el-switch
            v-model="showOnlyActive"
            active-text="Active only"
            inactive-text="Include archived"
          />
          <div v-if="(documentsData ?? []).length" class="document-list">
            <article
              class="document-card question-bank-card"
              :class="{ 'is-selected': store.selectedDocumentId === doc.document_id }"
              v-for="doc in documentsData ?? []"
              :key="doc.document_id"
              @click="selectDocument(doc.document_id)"
            >
              <div class="status-row">
                <span class="chip">{{ questionBankStatusLabel(doc.metadata) }}</span>
                <span class="chip">{{ questionBankQuestionCount(doc.metadata) }} questions</span>
              </div>
              <h4>{{ questionBankTitle(doc) }}</h4>
              <p class="muted-copy">{{ new Date(doc.created_at).toLocaleString() }}</p>
              <p class="muted-copy prewrap">{{ questionBankSummary(doc.metadata) }}</p>
              <div v-if="questionBankTopGaps(doc.metadata).length" class="pill-row">
                <span class="chip" v-for="gap in questionBankTopGaps(doc.metadata)" :key="gap">{{ gap }}</span>
              </div>
            </article>
          </div>
          <article v-else class="detail-card">
            <p class="muted-copy">No saved question banks yet.</p>
          </article>

          <article v-if="selectedQuestionBank" class="detail-card question-bank-detail">
            <div class="question-bank-detail__header">
              <div>
                <p class="eyebrow">Question bank</p>
                <h4>{{ questionBankTitle(selectedQuestionBank) }}</h4>
              </div>
              <div class="status-row">
                <span class="chip">{{ questionBankStatusLabel(selectedQuestionBank) }}</span>
                <span class="chip">{{ questionBankOverallLabel(selectedQuestionBank.overall_mastery) }}</span>
              </div>
            </div>
            <dl class="metadata-grid">
              <div v-if="metadataString(selectedQuestionBank.metadata, 'source_company')">
                <dt>Company</dt>
                <dd>{{ metadataString(selectedQuestionBank.metadata, "source_company") }}</dd>
              </div>
              <div v-if="metadataString(selectedQuestionBank.metadata, 'source_role')">
                <dt>Role</dt>
                <dd>{{ metadataString(selectedQuestionBank.metadata, "source_role") }}</dd>
              </div>
              <div>
                <dt>Created at</dt>
                <dd>{{ new Date(selectedQuestionBank.created_at).toLocaleString() }}</dd>
              </div>
              <div>
                <dt>Questions</dt>
                <dd>{{ selectedQuestionBank.question_count }}</dd>
              </div>
            </dl>
            <p v-if="selectedQuestionBank.summary" class="muted-copy prewrap">{{ selectedQuestionBank.summary }}</p>
            <div class="status-row">
              <span class="chip">strong {{ masteryCount(selectedQuestionBank.mastery_counts, "熟练掌握") }}</span>
              <span class="chip">partial {{ masteryCount(selectedQuestionBank.mastery_counts, "部分掌握") }}</span>
              <span class="chip">repair {{ masteryCount(selectedQuestionBank.mastery_counts, "需要加强") }}</span>
              <span class="chip">pending {{ masteryCount(selectedQuestionBank.mastery_counts, "未评估") }}</span>
            </div>
            <div v-if="selectedQuestionBank.top_gaps_found.length" class="pill-row">
              <span class="chip" v-for="gap in selectedQuestionBank.top_gaps_found" :key="gap">{{ gap }}</span>
            </div>
            <div v-if="selectedQuestionBank.records.length" class="question-feedback-list">
              <article
                class="question-feedback-card"
                v-for="record in selectedQuestionBank.records"
                :key="record.question_id"
              >
                <div class="question-feedback-card__header">
                  <div>
                    <p class="eyebrow">Question</p>
                    <h4>{{ record.question }}</h4>
                  </div>
                  <div class="status-row">
                    <span class="chip">{{ masteryTone(record.mastery_level, record.evaluation_status).label }}</span>
                    <span class="chip">{{ record.dimension }}</span>
                  </div>
                </div>
                <div v-if="record.topics.length" class="pill-row">
                  <span class="chip" v-for="topic in record.topics" :key="topic">{{ topic }}</span>
                </div>
                <section v-if="record.evaluation_status === 'pending'" class="detail-card question-feedback-card__summary">
                  <p class="eyebrow">Pending evaluation</p>
                  <p class="prewrap">
                    This set is already stored. Detailed scoring is still running question-by-question.
                  </p>
                </section>
                <div v-else class="question-score-grid">
                  <article class="detail-card question-score-card">
                    <p class="eyebrow">Accuracy</p>
                    <strong>{{ scoreLabel(record.accuracy_score) }}</strong>
                    <p class="muted-copy">{{ scoreValue(record.accuracy_score) }}/5</p>
                  </article>
                  <article class="detail-card question-score-card">
                    <p class="eyebrow">Structure</p>
                    <strong>{{ scoreLabel(record.structure_score) }}</strong>
                    <p class="muted-copy">{{ scoreValue(record.structure_score) }}/5</p>
                  </article>
                  <article class="detail-card question-score-card">
                    <p class="eyebrow">Depth</p>
                    <strong>{{ scoreLabel(record.depth_score) }}</strong>
                    <p class="muted-copy">{{ scoreValue(record.depth_score) }}/5</p>
                  </article>
                </div>
                <section v-if="record.score_summary" class="detail-card question-feedback-card__summary">
                  <p class="eyebrow">Coach summary</p>
                  <p class="prewrap">{{ record.score_summary }}</p>
                </section>
                <div v-if="record.evaluation_status !== 'pending'" class="question-feedback-grid">
                  <section class="detail-card">
                    <p class="eyebrow">Your answer</p>
                    <p class="prewrap">{{ record.user_answer || "No answer supplied." }}</p>
                  </section>
                  <section class="detail-card question-feedback-card__reference">
                    <p class="eyebrow">Reference answer</p>
                    <p class="prewrap">{{ record.reference_answer }}</p>
                  </section>
                </div>
                <div class="question-feedback-grid">
                  <section class="detail-card">
                    <p class="eyebrow">Missing or weak points</p>
                    <ul class="feedback-list">
                      <li v-for="gap in record.gaps" :key="gap">{{ gap }}</li>
                    </ul>
                  </section>
                  <section class="detail-card">
                    <p class="eyebrow">Suggested follow-up</p>
                    <ul class="feedback-list">
                      <li v-for="probe in record.next_probe" :key="probe">{{ probe }}</li>
                    </ul>
                  </section>
                </div>
              </article>
            </div>
          </article>
        </section>

        <section v-else class="panel section-stack">
          <div>
            <p class="eyebrow">History</p>
            <h3 class="section-title">Recent document snapshots</h3>
          </div>
          <el-switch
            v-model="showOnlyActive"
            active-text="Active only"
            inactive-text="Include inactive"
          />
          <div class="document-list">
            <article
              class="document-card"
              :class="{ 'is-selected': store.selectedDocumentId === doc.document_id }"
              v-for="doc in documentsData ?? []"
              :key="doc.document_id"
              @click="selectDocument(doc.document_id)"
            >
              <div class="status-row">
                <span class="chip">{{ doc.source_type }}</span>
                <span class="chip">{{ doc.is_active ? "active" : "inactive" }}</span>
              </div>
              <h4>{{ documentTitle(doc) }}</h4>
              <p class="muted-copy">{{ new Date(doc.created_at).toLocaleString() }}</p>
            </article>
          </div>

          <article v-if="selectedDocumentDetail" class="detail-card">
            <p class="eyebrow">Preview</p>
            <h4>{{ documentTitle(selectedDocumentDetail) }}</h4>
            <template v-if="selectedDocumentDetail.source_type === 'jd'">
              <dl class="metadata-grid">
                <div v-if="metadataString(selectedDocumentDetail.metadata, 'company')">
                  <dt>Company</dt>
                  <dd>{{ metadataString(selectedDocumentDetail.metadata, "company") }}</dd>
                </div>
                <div v-if="metadataString(selectedDocumentDetail.metadata, 'role')">
                  <dt>Role</dt>
                  <dd>{{ metadataString(selectedDocumentDetail.metadata, "role") }}</dd>
                </div>
                <div v-if="metadataString(selectedDocumentDetail.metadata, 'url')">
                  <dt>URL</dt>
                  <dd>
                    <a
                      :href="metadataString(selectedDocumentDetail.metadata, 'url')"
                      class="external-url"
                      target="_blank"
                      rel="noopener noreferrer"
                      :title="metadataString(selectedDocumentDetail.metadata, 'url')"
                    >
                      {{ formatUrlLabel(metadataString(selectedDocumentDetail.metadata, "url")) }}
                    </a>
                  </dd>
                </div>
                <div>
                  <dt>Created at</dt>
                  <dd>{{ new Date(selectedDocumentDetail.created_at).toLocaleString() }}</dd>
                </div>
              </dl>
              <template v-if="hasJdSections(selectedDocumentDetail.metadata)">
                <div v-if="metadataString(selectedDocumentDetail.metadata, 'job_description')">
                  <p class="eyebrow">Position description</p>
                  <pre class="raw-preview">{{ metadataString(selectedDocumentDetail.metadata, "job_description") }}</pre>
                </div>
                <div v-if="metadataString(selectedDocumentDetail.metadata, 'job_requirements')">
                  <p class="eyebrow">Position requirements</p>
                  <pre class="raw-preview">{{ metadataString(selectedDocumentDetail.metadata, "job_requirements") }}</pre>
                </div>
              </template>
              <pre v-else class="raw-preview">{{ selectedDocumentDetail.raw_text_preview }}</pre>
            </template>

            <template v-else>
              <dl class="metadata-grid">
                <div>
                  <dt>Created at</dt>
                  <dd>{{ new Date(selectedDocumentDetail.created_at).toLocaleString() }}</dd>
                </div>
              </dl>
              <pre class="raw-preview">{{ selectedDocumentDetail.raw_text_preview }}</pre>
            </template>
          </article>
        </section>
      </div>
    </section>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { ElMessage } from "element-plus";

import AppShell from "../components/AppShell.vue";
import CurrentJdPicker from "../components/CurrentJdPicker.vue";
import { useCurrentJdSelection } from "../composables/useCurrentJdSelection";
import { api, fileToBase64 } from "../lib/api";
import { useWorkbenchStore } from "../stores/workbench";

const LatexEditor = defineAsyncComponent(() => import("../components/LatexEditor.vue"));
const ResumePdfPreview = defineAsyncComponent(() => import("../components/ResumePdfPreview.vue"));
const RESUME_DIVIDER_WIDTH = 18;
const RESUME_PANE_MIN_WIDTH = 320;

const sourceNavItems = [
  {
    value: "resume",
    label: "Resume",
    description: "Overleaf-style LaTeX + PDF workspace",
  },
  {
    value: "jd",
    label: "JD",
    description: "Upload and manage target job descriptions",
  },
  {
    value: "question",
    label: "Questions",
    description: "Ingest question sets and answer history",
  },
] as const;

const store = useWorkbenchStore();
const queryClient = useQueryClient();
const { currentJd, currentJdLabel } = useCurrentJdSelection();
const showOnlyActive = ref(true);
const resumePdfVersion = ref(Date.now());
const pendingJdBase64 = ref<string>("");
const pendingJdFilename = ref<string>("");
const pendingQuestionBase64 = ref<string>("");
const pendingQuestionFilename = ref<string>("");
const lastResumeServerSource = ref("");
const resumeWorkspaceRef = ref<HTMLElement | null>(null);
const isNarrowViewport = ref(false);
const isDraggingDivider = ref(false);

const { data: resumeSourceData } = useQuery({
  queryKey: ["resume-source"],
  queryFn: () => api.getResumeSource(),
});

watch(
  () => resumeSourceData.value?.source,
  (source, previousSource) => {
    if (typeof source !== "string") {
      return;
    }
    if (!lastResumeServerSource.value || store.resumeDraft === (previousSource ?? lastResumeServerSource.value)) {
      store.resumeDraft = source;
    }
    lastResumeServerSource.value = source;
  },
  { immediate: true }
);

const { data: resumeCompileLogData } = useQuery({
  queryKey: ["resume-compile-log"],
  queryFn: () => api.getResumeCompileLog(),
  enabled: computed(() => store.currentSourceTab === "resume"),
});

const { data: documentsData } = useQuery({
  queryKey: computed(() => ["documents", store.currentSourceTab, showOnlyActive.value]),
  queryFn: () =>
    api.getDocuments({
      source_type: store.currentSourceTab,
      active_only: showOnlyActive.value,
      limit: 20,
    }),
  enabled: computed(() => store.currentSourceTab !== "resume"),
});

const { data: selectedDocumentDetail } = useQuery({
  queryKey: computed(() => ["document-detail", store.selectedDocumentId]),
  queryFn: () => api.getDocumentDetail(store.selectedDocumentId),
  enabled: computed(() => store.currentSourceTab === "jd" && Boolean(store.selectedDocumentId)),
});

const { data: selectedQuestionBank } = useQuery({
  queryKey: computed(() => ["question-bank-detail", store.selectedDocumentId]),
  queryFn: () => api.getQuestionBankDetail(store.selectedDocumentId),
  enabled: computed(() => store.currentSourceTab === "question" && Boolean(store.selectedDocumentId)),
});

const resumeSaveMutation = useMutation({
  mutationFn: () =>
    api.saveResumeSource({
      source: store.resumeDraft,
    }),
  onSuccess: async (data) => {
    store.resumeDraft = data.source;
    lastResumeServerSource.value = data.source;
    await queryClient.invalidateQueries({ queryKey: ["resume-source"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});

const resumeCompileMutation = useMutation({
  mutationFn: () => api.compileResume(),
  onSuccess: async (data) => {
    if (data.last_compile_status !== "success") {
      store.setResumeCompileLogExpanded(true);
    }
    if (data.pdf_exists && data.last_compile_status === "success") {
      resumePdfVersion.value = Date.now();
    }
    await queryClient.invalidateQueries({ queryKey: ["resume-source"] });
    await queryClient.invalidateQueries({ queryKey: ["resume-compile-log"] });
  },
});

const resumeSavePending = computed(() => resumeSaveMutation.isPending.value);
const resumeCompilePending = computed(() => resumeCompileMutation.isPending.value);
const resumeDirty = computed(() => store.resumeDraft !== (resumeSourceData.value?.source ?? ""));
const resumeStatus = computed(() => {
  if (resumeCompileMutation.data.value) {
    return resumeCompileMutation.data.value;
  }
  return {
    last_compiled_at: resumeSourceData.value?.last_compiled_at ?? null,
    last_compile_status: resumeSourceData.value?.last_compile_status ?? "not_run",
    last_compile_error_summary: resumeSourceData.value?.last_compile_error_summary ?? null,
    compiler_available: resumeSourceData.value?.compiler_available ?? false,
    pdf_exists: resumeSourceData.value?.pdf_exists ?? false,
    log_excerpt: "",
  };
});
const resumeCompileLog = computed(
  () => resumeCompileLogData.value || resumeCompileMutation.data.value?.log_excerpt || ""
);
const resumePdfUrl = computed(() => {
  const cacheKey = resumeStatus.value.last_compiled_at || String(resumePdfVersion.value);
  return `${api.getResumePdfUrl()}?t=${encodeURIComponent(cacheKey)}`;
});
const resumePdfWarning = computed(() => {
  if (!resumeStatus.value.pdf_exists) {
    return "";
  }
  if (resumeStatus.value.last_compile_status === "failed" || resumeStatus.value.last_compile_status === "missing_compiler") {
    return "Showing the most recent successful PDF because the latest compile did not produce a fresh one.";
  }
  return "";
});
const resumePdfEmptyMessage = computed(() => {
  if (resumeStatus.value.last_compile_status === "failed" || resumeStatus.value.last_compile_status === "missing_compiler") {
    return resumeStatus.value.last_compile_error_summary || "Compilation failed before a PDF could be produced.";
  }
  return "Compile the saved LaTeX source to generate a PDF preview here.";
});
const editorPaneWidthLabel = computed(() => `${Math.round(store.resumePaneRatio * 100)}% editor`);
const resumeEditorPaneStyle = computed(() => {
  if (isNarrowViewport.value) {
    return {};
  }
  return {
    flex: `0 0 ${resolveEditorWidth()}px`,
    maxWidth: `${resolveEditorWidth()}px`,
  };
});
const resumePreviewPaneStyle = computed(() => {
  if (isNarrowViewport.value) {
    return {};
  }
  const previewWidth = resolvePreviewWidth();
  return {
    flex: `0 0 ${previewWidth}px`,
    maxWidth: `${previewWidth}px`,
  };
});

const jdMutation = useMutation({
  mutationFn: () =>
    api.ingestJD({
      filename: pendingJdFilename.value || "jd.txt",
      content_base64: pendingJdBase64.value || undefined,
      company: store.jdCompanyDraft || undefined,
      role: store.jdRoleDraft || undefined,
      url: store.jdUrlDraft || undefined,
      job_description: store.jdDescriptionDraft || undefined,
      job_requirements: store.jdRequirementsDraft || undefined,
    }),
  onSuccess: async () => {
    pendingJdBase64.value = "";
    pendingJdFilename.value = "";
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
    await queryClient.invalidateQueries({ queryKey: ["jds"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});
const jdPending = computed(() => jdMutation.isPending.value);

const questionMutation = useMutation({
  mutationFn: () =>
    api.ingestQuestions({
      filename: pendingQuestionFilename.value || "questions.txt",
      text: store.questionDraft || undefined,
      content_base64: pendingQuestionBase64.value || undefined,
      source_company: store.questionCompanyDraft || undefined,
      source_role: store.questionRoleDraft || undefined,
      evaluate_answers: false,
    }),
  onSuccess: async (data) => {
    store.lastQuestionIngest = data;
    store.lastQuestionEvaluation = null;
    store.selectedDocumentId = data.document_id;
    store.questionDraft = "";
    pendingQuestionBase64.value = "";
    pendingQuestionFilename.value = "";
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
    questionEvaluateMutation.mutate(data.document_id);
  },
  onError: (error) => {
    ElMessage.error(extractErrorMessage(error));
  },
});
const questionPending = computed(() => questionMutation.isPending.value);
const questionSubmitPending = computed(() => questionPending.value || questionEvaluatePending.value);
const questionEvaluateMutation = useMutation({
  mutationFn: (documentId: string) => api.evaluateQuestions(documentId),
  onSuccess: async (data) => {
    store.lastQuestionEvaluation = data;
    store.selectedDocumentId = data.document_id;
    await queryClient.invalidateQueries({ queryKey: ["question-bank-detail", data.document_id] });
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
    await queryClient.invalidateQueries({ queryKey: ["diagnosis"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
  onError: (error) => {
    ElMessage.error(extractErrorMessage(error));
  },
});
const questionEvaluatePending = computed(() => questionEvaluateMutation.isPending.value);
const questionWorkflowStatus = computed(() => {
  if (questionPending.value) {
    return {
      title: "Saving question set",
      badge: "saving",
      description: "Parsing the pasted content and writing the latest question set into this workspace.",
    };
  }
  if (questionEvaluatePending.value) {
    return {
      title: "Evaluating answers one by one",
      badge: "evaluating",
      description:
        "The set is already saved. Detailed scoring is running question-by-question, so this step can take longer.",
    };
  }
  if (!store.lastQuestionIngest) {
    return null;
  }
  if (store.lastQuestionEvaluation) {
    return {
      title: "Evaluation finished",
      badge: "evaluated",
      description:
        "This set is now in the question bank below. Open the card to review question-by-question feedback.",
      };
  }
  return {
    title: "Saved, preparing evaluation",
    badge: "saved",
    description: "The set is stored already and is about to continue into question-by-question evaluation.",
  };
});

const resumeTailorMutation = useMutation({
  mutationFn: () => api.getResumeTailorDraft(store.selectedJdId || undefined),
});
const resumeTailorPending = computed(() => resumeTailorMutation.isPending.value);
const resumeTailorDraft = computed(() => resumeTailorMutation.data.value || null);

watch(
  () => store.currentSourceTab,
  () => {
    store.selectedDocumentId = "";
  }
);

watch(
  () => store.selectedJdId,
  () => {
    resumeTailorMutation.reset();
  }
);

watch(
  () => documentsData.value,
  (documents) => {
    if (!store.selectedDocumentId || !documents?.length) {
      return;
    }
    const stillVisible = documents.some((item) => item.document_id === store.selectedDocumentId);
    if (!stillVisible) {
      store.selectedDocumentId = "";
    }
  }
);

onMounted(() => {
  syncViewportMode();
  window.addEventListener("resize", syncViewportMode);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", syncViewportMode);
  stopResumePaneResize();
});

function selectDocument(documentId: string) {
  store.selectedDocumentId = store.selectedDocumentId === documentId ? "" : documentId;
}

async function onJdFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  pendingJdBase64.value = await fileToBase64(file);
  pendingJdFilename.value = file.name;
}

async function onQuestionFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  pendingQuestionBase64.value = await fileToBase64(file);
  pendingQuestionFilename.value = file.name;
}

function submitResumeSource() {
  resumeSaveMutation.mutate();
}

function submitResumeCompile() {
  resumeCompileMutation.mutate();
}

function submitJd() {
  jdMutation.mutate();
}

function submitQuestions() {
  questionMutation.mutate();
}

function generateResumeTailorDraft() {
  resumeTailorMutation.mutate();
}

function toggleResumeCompileLog() {
  store.setResumeCompileLogExpanded(!store.resumeCompileLogExpanded);
}

function formatTimestamp(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

function metadataString(metadata: Record<string, unknown>, key: string): string {
  const value = metadata[key];
  return typeof value === "string" ? value : "";
}

function hasJdSections(metadata: Record<string, unknown>): boolean {
  return Boolean(
    metadataString(metadata, "job_description") || metadataString(metadata, "job_requirements")
  );
}

function formatUrlLabel(value: string): string {
  if (!value) {
    return "";
  }
  try {
    const parsed = new URL(value);
    const path = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
    const compact = `${parsed.hostname}${path}`;
    return compact.length > 56 ? `${compact.slice(0, 53)}...` : compact;
  } catch {
    return value.length > 56 ? `${value.slice(0, 53)}...` : value;
  }
}

function documentTitle(document: {
  document_id: string;
  filename: string | null;
  metadata: Record<string, unknown>;
  source_type: string;
}): string {
  if (document.source_type === "jd") {
    const role = metadataString(document.metadata, "role");
    const company = metadataString(document.metadata, "company");
    if (company && role) {
      return `${company} · ${role}`;
    }
    if (role || company) {
      return role || company;
    }
  }
  return document.filename || document.document_id;
}

function questionBankTitle(document: {
  document_id: string;
  filename: string | null;
  metadata: Record<string, unknown>;
}): string {
  const company = metadataString(document.metadata, "source_company");
  const role = metadataString(document.metadata, "source_role");
  const sourceScope = metadataString(document.metadata, "source_scope");
  if (company && role) {
    return `${company} · ${role}`;
  }
  if (role || company) {
    return role || company;
  }
  if (sourceScope) {
    return sourceScope;
  }
  return document.filename || document.document_id;
}

function questionBankSummary(metadata: Record<string, unknown>): string {
  const summary = metadataString(metadata, "summary");
  if (summary) {
    return summary;
  }
  const questionCount = questionBankQuestionCount(metadata);
  if (!questionCount) {
    return "No parsed questions yet.";
  }
  return `${questionCount} saved questions.`;
}

function questionBankStatusLabel(
  metadata: Record<string, unknown> | { metadata: Record<string, unknown>; evaluation_status: string }
): string {
  let value = "";
  if ("metadata" in metadata) {
    const detail = metadata as { metadata: Record<string, unknown>; evaluation_status: string };
    value = metadataString(detail.metadata, "evaluation_status") || detail.evaluation_status;
  } else {
    value = metadataString(metadata as Record<string, unknown>, "evaluation_status");
  }
  if (value === "completed") {
    return "evaluated";
  }
  if (value === "partial") {
    return "partially evaluated";
  }
  return "awaiting evaluation";
}

function questionBankOverallLabel(value: string | null | undefined): string {
  if (value === "mostly_strong") {
    return "mostly strong";
  }
  if (value === "repair_priority") {
    return "repair priority";
  }
  if (value === "mixed") {
    return "mixed mastery";
  }
  if (value === "awaiting_evaluation") {
    return "awaiting evaluation";
  }
  if (value === "empty") {
    return "empty set";
  }
  return "question bank";
}

function questionBankQuestionCount(metadata: Record<string, unknown>): number {
  const value = metadata["question_count"];
  return typeof value === "number" ? value : 0;
}

function questionBankTopGaps(metadata: Record<string, unknown>): string[] {
  const value = metadata["top_gaps_found"];
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean)
    .slice(0, 3);
}

function masteryCount(masteryCounts: Record<string, number>, key: string): number {
  const value = masteryCounts[key];
  return typeof value === "number" ? value : 0;
}

function masteryTone(masteryLevel: string, evaluationStatus = "completed"): { label: string } {
  if (evaluationStatus === "pending") {
    return { label: "awaiting evaluation" };
  }
  if (masteryLevel === "熟练掌握") {
    return { label: "strong answer" };
  }
  if (masteryLevel === "部分掌握") {
    return { label: "needs more depth" };
  }
  return { label: "repair this answer" };
}

function scoreValue(score: number | null): string {
  if (typeof score !== "number") {
    return "--";
  }
  return String(Math.min(5, Math.max(1, Math.round(score))));
}

function scoreLabel(score: number | null): string {
  if (typeof score !== "number") {
    return "Pending";
  }
  const normalized = Math.min(5, Math.max(1, Math.round(score)));
  if (normalized >= 4) {
    return "Strong";
  }
  if (normalized === 3) {
    return "Mixed";
  }
  return "Weak";
}

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Request failed. Check the backend logs for details.";
}

function syncViewportMode() {
  isNarrowViewport.value = window.innerWidth < 1180;
}

function resolveEditorWidth(): number {
  const container = resumeWorkspaceRef.value;
  if (!container) {
    return 560;
  }
  const availableWidth = container.clientWidth - RESUME_DIVIDER_WIDTH;
  if (availableWidth <= RESUME_PANE_MIN_WIDTH * 2) {
    return Math.max(RESUME_PANE_MIN_WIDTH, Math.floor(availableWidth / 2));
  }
  const rawWidth = availableWidth * store.resumePaneRatio;
  return Math.round(
    Math.min(
      availableWidth - RESUME_PANE_MIN_WIDTH,
      Math.max(RESUME_PANE_MIN_WIDTH, rawWidth)
    )
  );
}

function resolvePreviewWidth(): number {
  const container = resumeWorkspaceRef.value;
  if (!container) {
    return 700;
  }
  const availableWidth = container.clientWidth - RESUME_DIVIDER_WIDTH;
  return Math.max(RESUME_PANE_MIN_WIDTH, availableWidth - resolveEditorWidth());
}

function startResumePaneResize(event: PointerEvent) {
  if (isNarrowViewport.value) {
    return;
  }
  event.preventDefault();
  isDraggingDivider.value = true;
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
  window.addEventListener("pointermove", handleResumePaneResize);
  window.addEventListener("pointerup", stopResumePaneResize);
}

function handleResumePaneResize(event: PointerEvent) {
  const container = resumeWorkspaceRef.value;
  if (!container) {
    return;
  }
  const rect = container.getBoundingClientRect();
  const availableWidth = rect.width - RESUME_DIVIDER_WIDTH;
  if (availableWidth <= RESUME_PANE_MIN_WIDTH * 2) {
    return;
  }
  const rawRatio = (event.clientX - rect.left) / availableWidth;
  const minRatio = RESUME_PANE_MIN_WIDTH / availableWidth;
  const maxRatio = 1 - minRatio;
  store.setResumePaneRatio(Math.min(maxRatio, Math.max(minRatio, rawRatio)));
}

function stopResumePaneResize() {
  isDraggingDivider.value = false;
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  window.removeEventListener("pointermove", handleResumePaneResize);
  window.removeEventListener("pointerup", stopResumePaneResize);
}
</script>

<style scoped>
.sources-sidebar-block {
  display: grid;
  gap: 16px;
}

.source-nav {
  display: grid;
  gap: 10px;
}

.source-nav__button {
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.56);
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
}

.source-nav__button:hover {
  transform: translateY(-1px);
  border-color: rgba(189, 94, 44, 0.28);
  background: rgba(255, 255, 255, 0.78);
}

.source-nav__button.is-active {
  border-color: rgba(189, 94, 44, 0.32);
  background: rgba(189, 94, 44, 0.1);
}

.source-nav__title {
  font-size: 15px;
  font-weight: 700;
}

.source-nav__copy,
.sources-sidebar-status__meta {
  font-size: 13px;
  color: var(--ink-soft);
  line-height: 1.5;
}

.sources-sidebar-status {
  display: grid;
  gap: 12px;
}

.sources-sidebar-status__chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.sources-sidebar-status__actions {
  display: grid;
  gap: 10px;
}

.sources-stage {
  min-width: 0;
}

.sources-stack-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 20px;
}

.external-url {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-word;
}

:deep(.document-card.is-selected) {
  border-color: rgba(189, 94, 44, 0.32);
  background: rgba(189, 94, 44, 0.08);
}

.resume-workspace {
  display: flex;
  align-items: stretch;
  gap: 0;
  min-height: calc(100vh - 176px);
}

.resume-editor-pane,
.resume-preview-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 18px;
}

.resume-pane__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.resume-pane__body {
  min-height: 0;
  flex: 1;
}

.resume-preview-pane {
  min-width: 0;
  gap: 16px;
}

.resume-preview-surface {
  flex: 1 1 auto;
  min-height: 640px;
}

.resume-divider {
  position: relative;
  z-index: 2;
  flex: 0 0 18px;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
}

.resume-divider::before {
  content: "";
  position: absolute;
  inset: 0;
}

.resume-divider__handle {
  width: 6px;
  height: 88px;
  border-radius: 999px;
  background: rgba(189, 94, 44, 0.18);
  box-shadow: inset 0 0 0 1px rgba(189, 94, 44, 0.18);
}

.resume-divider.is-dragging .resume-divider__handle,
.resume-divider:hover .resume-divider__handle {
  background: rgba(189, 94, 44, 0.42);
}

.resume-log-card {
  display: grid;
  gap: 14px;
}

.resume-log-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.resume-log-card__body {
  max-height: 240px;
  overflow: auto;
}

.resume-tailor-card {
  display: grid;
  gap: 14px;
}

.question-bank-card,
.question-workflow-card {
  display: grid;
  gap: 12px;
}

.question-workflow-card {
  background: rgba(218, 119, 55, 0.08);
}

.question-workflow-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.question-bank-detail {
  display: grid;
  gap: 16px;
}

.question-bank-detail__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.question-feedback-list,
.question-feedback-card,
.question-feedback-grid {
  display: grid;
  gap: 14px;
}

.question-feedback-card {
  padding-top: 6px;
  border-top: 1px solid rgba(109, 88, 74, 0.14);
}

.question-feedback-card:first-child {
  padding-top: 0;
  border-top: 0;
}

.question-feedback-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.question-feedback-card__reference {
  background: rgba(189, 94, 44, 0.08);
}

.question-feedback-card__summary {
  background: rgba(218, 119, 55, 0.08);
}

.question-score-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.question-score-card {
  gap: 6px;
}

.feedback-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 8px;
}

.tailor-list {
  margin: 0;
  padding-left: 18px;
}

@media (max-width: 1180px) {
  .resume-workspace {
    flex-direction: column;
    gap: 16px;
    min-height: auto;
  }
}

@media (max-width: 768px) {
  .source-nav__button {
    padding: 12px 14px;
  }

  .question-bank-detail__header,
  .question-workflow-card__header,
  .question-feedback-card__header {
    flex-direction: column;
  }

  .question-score-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
