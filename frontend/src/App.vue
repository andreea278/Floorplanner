<script setup lang="ts">
import { ref } from 'vue'
import ThreeViewer from './components/ThreeViewer.vue'
import PdfUploader from './components/PdfUploader.vue'
import FloorPlanEditor from './components/FloorPlanEditor.vue'
import type { FloorPlan } from '@/types/floorPlan'

// Three stages, one flag each - only one is ever true at a time:
//   1. detectedPlan === null                -> show the uploader
//   2. detectedPlan set, confirmedPlan null  -> show the 2D editor
//   3. confirmedPlan set                     -> show the 3D viewer
const detectedPlan = ref<FloorPlan | null>(null)
const confirmedPlan = ref<FloorPlan | null>(null)

function onDetected(result: FloorPlan) {
  detectedPlan.value = result
}

function onConfirmed(edited: FloorPlan) {
  confirmedPlan.value = edited
}

function reset() {
  detectedPlan.value = null
  confirmedPlan.value = null
}

function backTo2D() {
  confirmedPlan.value = null
}
</script>

<template>
  <main class="app">
    <div v-if="!detectedPlan" class="upload-screen">
      <h1>Floorplaner</h1>
      <p class="tagline">Upload a floorplan to generate a 3D model</p>
      <PdfUploader @detected="onDetected" />
    </div>

    <div v-else-if="!confirmedPlan" class="review-screen">
      <FloorPlanEditor :floor-plan="detectedPlan" @confirm="onConfirmed" />
      <button class="reset-button" @click="reset">Start over</button>
    </div>

    <template v-else>
      <ThreeViewer :floor-plan="confirmedPlan" />
      <button class="reset-button" @click="backTo2D">← Back to 2D</button>
      <button class="reset-button secondary" @click="reset">Upload another plan</button>
    </template>
  </main>
</template>

<style scoped>
.app {
  width: 100vw;
  height: 100vh;
  margin: 0;
  position: relative;
}

.upload-screen,
.review-screen {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #101012;
  color: #e5e5e5;
  overflow: auto;
}

.upload-screen h1 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.tagline {
  margin: 0 0 20px 0;
  color: #888;
  font-size: 14px;
}

.reset-button {
  position: absolute;
  top: 16px;
  left: 16px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid #444;
  background: #1c1c1e;
  color: #e5e5e5;
  font-size: 13px;
  cursor: pointer;
}

.reset-button.secondary {
  left: 160px;
}

.reset-button:hover {
  border-color: #6b8afd;
}
</style>