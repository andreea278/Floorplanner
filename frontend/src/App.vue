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

function startBlank() {
  detectedPlan.value = {
    id: `floorplan-${crypto.randomUUID().slice(0, 8)}`,
    name: 'New Floor Plan',
    unit: 'meters',
    walls: [],
  }
}

// IMPORTANT: update BOTH refs. FloorPlanEditor re-reads its starting walls
// from `detectedPlan` every time it mounts (including when we come back
// from the 3D view), so if only `confirmedPlan` were updated here, going
// "Back to 2D" would re-mount the editor with the original, pre-edit walls
// and silently discard everything drawn/edited so far.
function onConfirmed(edited: FloorPlan) {
  detectedPlan.value = edited
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
      <div class="brand">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M3 21V8L12 3L21 8V21H14V14H10V21H3Z"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linejoin="round"
            />
          </svg>
        </div>
        <h1>Floorplaner</h1>
      </div>
      <p class="tagline">Upload a floorplan or start with a blank canvas</p>

      <PdfUploader @detected="onDetected" />

      <div class="divider"><span>or</span></div>

      <button class="blank-button" @click="startBlank">
        <span class="plus">+</span> Start from scratch
      </button>
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
  background: radial-gradient(circle at 50% 0%, #17171b 0%, #101012 60%);
  color: #e5e5e5;
  overflow: auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 2px;
}

.brand-icon {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b8afd;
}

.brand-icon svg {
  width: 100%;
  height: 100%;
}

.upload-screen h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.tagline {
  margin: 0 0 24px 0;
  color: #888;
  font-size: 14px;
}

.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 420px;
  margin: 18px 0;
  color: #555;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #2a2a2e;
}

.blank-button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-radius: 10px;
  border: 1px solid #333;
  background: #1c1c1e;
  color: #e5e5e5;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.blank-button:hover {
  border-color: #6b8afd;
  background: #22242e;
}

.blank-button .plus {
  color: #6b8afd;
  font-weight: 700;
  font-size: 16px;
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