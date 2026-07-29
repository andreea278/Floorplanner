<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { FloorPlan, Wall } from '@/types/floorPlan'

const props = defineProps<{
  floorPlan: FloorPlan
}>()

const containerRef = ref<HTMLDivElement | null>(null)

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: OrbitControls
let animationFrameId = 0

const wallMeshes: THREE.Mesh[] = []

function createWallMesh(wall: Wall): THREE.Mesh {
  const dx = wall.end.x - wall.start.x
  const dz = wall.end.y - wall.start.y

  const length = Math.hypot(dx, dz)
  const angle = Math.atan2(dz, dx)

  const geometry = new THREE.BoxGeometry(length, wall.height, wall.thickness)

  const material = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.6,
  })

  const mesh = new THREE.Mesh(geometry, material)

  mesh.position.set(
    (wall.start.x + wall.end.x) / 2,
    wall.height / 2,
    (wall.start.y + wall.end.y) / 2,
  )

  mesh.rotation.y = -angle

  return mesh
}

function clearWalls() {
  for (const mesh of wallMeshes) {
    scene.remove(mesh)
    mesh.geometry.dispose()

    if (Array.isArray(mesh.material)) {
      mesh.material.forEach((material) => material.dispose())
    } else {
      mesh.material.dispose()
    }
  }

  wallMeshes.length = 0
}

function renderWalls(floorPlan: FloorPlan) {
  clearWalls()

  for (const wall of floorPlan.walls) {
    const wallMesh = createWallMesh(wall)
    wallMeshes.push(wallMesh)
    scene.add(wallMesh)
  }
}

function createFloor() {
  const floorGeometry = new THREE.PlaneGeometry(50, 50)

  const floorMaterial = new THREE.MeshStandardMaterial({
    color: 0xdddddd,
    roughness: 0.8,
  })

  const floor = new THREE.Mesh(floorGeometry, floorMaterial)
  floor.rotation.x = -Math.PI / 2
  floor.position.set(5, 0, 5)

  scene.add(floor)
}

function createLights() {
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.5)
  scene.add(ambientLight)

  const directionalLight = new THREE.DirectionalLight(0xffffff, 1.5)
  directionalLight.position.set(5, 10, 5)
  scene.add(directionalLight)
}

function createGrid() {
  const grid = new THREE.GridHelper(50, 50)
  grid.position.set(5, 0.01, 5)
  scene.add(grid)
}

function handleResize() {
  if (!containerRef.value) {
    return
  }

  const width = containerRef.value.clientWidth
  const height = containerRef.value.clientHeight

  camera.aspect = width / height
  camera.updateProjectionMatrix()

  renderer.setSize(width, height)
}

function animate() {
  animationFrameId = requestAnimationFrame(animate)

  controls.update()
  renderer.render(scene, camera)
}

onMounted(() => {
  if (!containerRef.value) {
    return
  }

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xf3f4f6)

  const width = containerRef.value.clientWidth
  const height = containerRef.value.clientHeight

  camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000)
  camera.position.set(8, 7, 8)

  renderer = new THREE.WebGLRenderer({
    antialias: true,
  })

  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)

  containerRef.value.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.target.set(3, 1, 2)

  createFloor()
  createGrid()
  createLights()
  renderWalls(props.floorPlan)

  window.addEventListener('resize', handleResize)

  animate()
})

watch(
  () => props.floorPlan,
  (newFloorPlan) => {
    if (!scene) {
      return
    }

    renderWalls(newFloorPlan)
  },
  { deep: true },
)

onUnmounted(() => {
  cancelAnimationFrame(animationFrameId)
  window.removeEventListener('resize', handleResize)

  clearWalls()

  controls?.dispose()
  renderer?.dispose()
})
</script>

<template>
  <div ref="containerRef" class="three-viewer"></div>
</template>

<style scoped>
.three-viewer {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}
</style>