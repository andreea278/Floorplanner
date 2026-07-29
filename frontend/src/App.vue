<script setup lang="ts">
import ThreeViewer from './components/ThreeViewer.vue'
import { mockFloorPlan } from './data/mockFloorPlan'
</script>

<template>
  <main class="app">
    <ThreeViewer :floor-plan="mockFloorPlan" />
  </main>
</template>

<style scoped>
.app {
  width: 100vw;
  height: 100vh;
  margin: 0;
}
</style>