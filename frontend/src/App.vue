<script setup lang="ts">
import { ref } from 'vue'
import ThreeViewer from './components/ThreeViewer.vue'
import PdfUploader from './components/PdfUploader.vue'
import type { FloorPlan } from '@/types/floorPlan'

const floorPlan = ref<FloorPlan | null>(null)

function onDetected(result: FloorPlan) {
  floorPlan.value = result
}

function reset() {
  floorPlan.value = null
}
</script>

<template>
  <main class="app">
    <div v-if="!floorPlan" class="upload-screen">
      <h1>Floorplaner</h1>
      <p class="tagline">Upload a floorplan to generate a 3D model</p>
      <PdfUploader @detected="onDetected" />
    </div>

    <template v-else>
      <ThreeViewer :floor-plan="floorPlan" />
      <button class="reset-button" @click="reset">Upload another plan</button>
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

.upload-screen {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #101012;
  color: #e5e5e5;
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

.reset-button:hover {
  border-color: #6b8afd;
}
</style>
