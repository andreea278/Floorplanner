<script setup lang="ts">
import { ref } from 'vue'
import type { FloorPlan } from '@/types/floorPlan'
import { detectFloorPlan, FloorPlanApiError } from '@/services/floorPlanApi'

const emit = defineEmits<{
  detected: [floorPlan: FloorPlan]
}>()

const ACCEPTED_TYPES = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp']

const isDragging = ref(false)
const isUploading = ref(false)
const errorMessage = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function openFileDialog() {
  fileInput.value?.click()
}

function onFileInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) handleFile(file)
  target.value = ''
}

function onDrop(event: DragEvent) {
  isDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

async function handleFile(file: File) {
  errorMessage.value = null

  if (!ACCEPTED_TYPES.includes(file.type)) {
    errorMessage.value = 'Unsupported file type. Upload a PDF, PNG, or JPEG.'
    return
  }

  isUploading.value = true
  try {
    const floorPlan = await detectFloorPlan(file)
    emit('detected', floorPlan)
  } catch (err) {
    errorMessage.value =
      err instanceof FloorPlanApiError ? err.message : 'Something went wrong during detection.'
  } finally {
    isUploading.value = false
  }
}
</script>

<template>
  <div class="uploader">
    <div
      class="dropzone"
      :class="{ dragging: isDragging, uploading: isUploading }"
      @click="openFileDialog"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.webp"
        class="hidden-input"
        @change="onFileInputChange"
      />

      <div v-if="isUploading" class="state">
        <div class="spinner" />
        <p class="title">Detecting walls…</p>
      </div>

      <div v-else class="state">
        <svg class="upload-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12 16V4M12 4L7 9M12 4L17 9"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M4 16V18C4 19.1046 4.89543 20 6 20H18C19.1046 20 20 19.1046 20 18V16"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <p class="title">Drop a floorplan here</p>
        <p class="subtitle">PDF, PNG, or JPEG — or click to browse</p>
      </div>
    </div>

    <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
  </div>
</template>

<style scoped>
.uploader {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 420px;
}

.dropzone {
  width: 100%;
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed #444;
  border-radius: 14px;
  background: #1c1c1e;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    transform 0.15s ease;
}

.dropzone:hover {
  border-color: #6b8afd;
  transform: translateY(-1px);
}

.dropzone.dragging {
  border-color: #6b8afd;
  background: #22242e;
}

.dropzone.uploading {
  cursor: default;
  border-color: #444;
  transform: none;
}

.hidden-input {
  display: none;
}

.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #e5e5e5;
  text-align: center;
  padding: 24px;
}

.upload-icon {
  width: 30px;
  height: 30px;
  color: #6b8afd;
  margin-bottom: 4px;
}

.title {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.subtitle {
  font-size: 13px;
  color: #888;
  margin: 0;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #333;
  border-top-color: #6b8afd;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error {
  color: #ff6b6b;
  font-size: 13px;
  margin: 0;
  text-align: center;
}
</style>