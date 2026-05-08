<template>
  <AppShell title="Sources">
    <div class="split-layout">
      <section class="panel section-stack">
        <div>
          <p class="eyebrow">Ingestion</p>
          <h3 class="section-title">Upload or paste core prep materials</h3>
        </div>

        <el-tabs v-model="store.currentSourceTab">
          <el-tab-pane label="Resume" name="resume">
            <div class="section-stack">
              <el-input
                v-model="store.resumeDraft"
                type="textarea"
                :rows="10"
                placeholder="Paste your latest resume or project summary here."
              />
              <input type="file" @change="onResumeFile" />
              <div class="form-actions">
                <el-button type="primary" :loading="resumePending" @click="submitResume">
                  Save resume
                </el-button>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="JD" name="jd">
            <div class="section-stack">
              <el-input v-model="store.jdCompanyDraft" placeholder="Company" />
              <el-input v-model="store.jdRoleDraft" placeholder="Role" />
              <el-input
                v-model="store.jdDraft"
                type="textarea"
                :rows="10"
                placeholder="Paste the job description text."
              />
              <input type="file" @change="onJdFile" />
              <div class="form-actions">
                <el-button type="primary" :loading="jdPending" @click="submitJd">
                  Save JD
                </el-button>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="Questions" name="question">
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
                <el-button type="primary" :loading="questionPending" @click="submitQuestions">
                  Save question set
                </el-button>
              </div>
              <article v-if="store.lastQuestionIngest" class="detail-card">
                <p class="eyebrow">Latest ingest result</p>
                <p class="muted-copy">
                  processed={{ store.lastQuestionIngest.processed_count }},
                  deduped={{ store.lastQuestionIngest.deduped_count }},
                  skipped={{ store.lastQuestionIngest.skipped_count }},
                  inactive={{ store.lastQuestionIngest.inactive_count }}
                </p>
                <div class="pill-row">
                  <span class="chip" v-for="gap in store.lastQuestionIngest.top_gaps_found" :key="gap">
                    {{ gap }}
                  </span>
                </div>
              </article>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>

      <section class="panel section-stack">
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
            v-for="doc in documentsData ?? []"
            :key="doc.document_id"
            @click="selectDocument(doc.document_id)"
          >
            <div class="status-row">
              <span class="chip">{{ doc.source_type }}</span>
              <span class="chip">{{ doc.is_active ? "active" : "inactive" }}</span>
            </div>
            <h4>{{ doc.filename || doc.document_id }}</h4>
            <p class="muted-copy">{{ new Date(doc.created_at).toLocaleString() }}</p>
          </article>
        </div>

        <article v-if="selectedDocument" class="detail-card">
          <p class="eyebrow">Preview</p>
          <h4>{{ selectedDocument.filename || selectedDocument.document_id }}</h4>
          <dl class="metadata-grid">
            <div>
              <dt>Content hash</dt>
              <dd>{{ selectedDocument.content_hash }}</dd>
            </div>
            <div>
              <dt>Created at</dt>
              <dd>{{ new Date(selectedDocument.created_at).toLocaleString() }}</dd>
            </div>
          </dl>
          <pre class="raw-preview">{{ selectedDocument.raw_text_preview }}</pre>
        </article>
      </section>
    </div>
  </AppShell>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";

import AppShell from "../components/AppShell.vue";
import { api, fileToBase64 } from "../lib/api";
import { useWorkbenchStore } from "../stores/workbench";

const store = useWorkbenchStore();
const queryClient = useQueryClient();
const showOnlyActive = ref(true);
const pendingResumeBase64 = ref<string>("");
const pendingResumeFilename = ref<string>("");
const pendingJdBase64 = ref<string>("");
const pendingJdFilename = ref<string>("");
const pendingQuestionBase64 = ref<string>("");
const pendingQuestionFilename = ref<string>("");

const { data: documentsData } = useQuery({
  queryKey: computed(() => ["documents", store.currentSourceTab, showOnlyActive.value]),
  queryFn: () =>
    api.getDocuments({
      source_type: store.currentSourceTab,
      active_only: showOnlyActive.value,
      limit: 20,
    }),
});

const { data: selectedDocument } = useQuery({
  queryKey: computed(() => ["document-detail", store.selectedDocumentId]),
  queryFn: () => api.getDocumentDetail(store.selectedDocumentId),
  enabled: computed(() => Boolean(store.selectedDocumentId)),
});

const resumeMutation = useMutation({
  mutationFn: () =>
    api.ingestResume({
      filename: pendingResumeFilename.value || "resume.txt",
      text: store.resumeDraft || undefined,
      content_base64: pendingResumeBase64.value || undefined,
    }),
  onSuccess: async () => {
    pendingResumeBase64.value = "";
    pendingResumeFilename.value = "";
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});
const resumePending = computed(() => resumeMutation.isPending.value);

const jdMutation = useMutation({
  mutationFn: () =>
    api.ingestJD({
      filename: pendingJdFilename.value || "jd.txt",
      text: store.jdDraft || undefined,
      content_base64: pendingJdBase64.value || undefined,
      company: store.jdCompanyDraft || undefined,
      role: store.jdRoleDraft || undefined,
    }),
  onSuccess: async () => {
    pendingJdBase64.value = "";
    pendingJdFilename.value = "";
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
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
    }),
  onSuccess: async (data) => {
    store.lastQuestionIngest = data;
    pendingQuestionBase64.value = "";
    pendingQuestionFilename.value = "";
    await queryClient.invalidateQueries({ queryKey: ["documents"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  },
});
const questionPending = computed(() => questionMutation.isPending.value);

function selectDocument(documentId: string) {
  store.selectedDocumentId = documentId;
}

async function onResumeFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  pendingResumeBase64.value = await fileToBase64(file);
  pendingResumeFilename.value = file.name;
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

function submitResume() {
  resumeMutation.mutate();
}

function submitJd() {
  jdMutation.mutate();
}

function submitQuestions() {
  questionMutation.mutate();
}
</script>
