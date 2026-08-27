<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { useWalkControls } from '@/composables/useWalkControls'
import type { FloorPlan, Wall } from '@/types/floorPlan'

const props = defineProps<{
  floorPlan: FloorPlan
}>()

const containerRef = ref<HTMLDivElement | null>(null)

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: OrbitControls
let walkControls: ReturnType<typeof useWalkControls>
let animationFrameId = 0

const clock = new THREE.Clock()

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

// The camera/target used to be hardcoded, tuned only for the original
// 10x4m mock rectangle - any differently-sized or off-center plan orbited
// around an arbitrary pivot point, which made far parts of the model swing
// wildly out of view while rotating. This computes the plan's actual
// bounding box and frames the camera around its true center every time a
// plan loads or changes. Walk controls (WASD) then move the camera AND
// this target together from wherever framing put them, so orbiting always
// pivots around your current position once you've moved.
function frameCameraToPlan(floorPlan: FloorPlan) {
  if (floorPlan.walls.length === 0) return

  const xs = floorPlan.walls.flatMap((w) => [w.start.x, w.end.x])
  const zs = floorPlan.walls.flatMap((w) => [w.start.y, w.end.y])
  const maxHeight = Math.max(...floorPlan.walls.map((w) => w.height))

  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minZ = Math.min(...zs)
  const maxZ = Math.max(...zs)

  const centerX = (minX + maxX) / 2
  const centerZ = (minZ + maxZ) / 2
  const centerY = maxHeight / 2

  const diagonal = Math.hypot(maxX - minX, maxZ - minZ, maxHeight)
  const distance = Math.max(diagonal * 1.1, 5)

  controls.target.set(centerX, centerY, centerZ)
  camera.position.set(
    centerX + distance * 0.6,
    centerY + distance * 0.55,
    centerZ + distance * 0.6,
  )
  camera.near = Math.max(distance / 1000, 0.01)
  camera.far = distance * 100
  camera.updateProjectionMatrix()
  controls.update()
}

let floorMesh: THREE.Mesh
const floorMaterial = new THREE.MeshStandardMaterial({
  color: 0xdddddd,
  roughness: 0.8,
})

function createFloor() {
  floorMesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), floorMaterial)
  floorMesh.rotation.x = -Math.PI / 2
  scene.add(floorMesh)
}

function createLights() {
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.5)
  scene.add(ambientLight)

  const directionalLight = new THREE.DirectionalLight(0xffffff, 1.5)
  directionalLight.position.set(5, 10, 5)
  scene.add(directionalLight)
}

let gridHelper: THREE.GridHelper | null = null

function createGrid() {
  gridHelper = new THREE.GridHelper(1, 1)
  scene.add(gridHelper)
}

function fitGroundToPlan(floorPlan: FloorPlan) {
  if (floorPlan.walls.length === 0) return

  const xs = floorPlan.walls.flatMap((w) => [w.start.x, w.end.x])
  const zs = floorPlan.walls.flatMap((w) => [w.start.y, w.end.y])

  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minZ = Math.min(...zs)
  const maxZ = Math.max(...zs)

  const centerX = (minX + maxX) / 2
  const centerZ = (minZ + maxZ) / 2
  const margin = Math.max(maxX - minX, maxZ - minZ) * 0.6 + 5
  const size = Math.max(maxX - minX, maxZ - minZ, 1) + margin * 2

  floorMesh.geometry.dispose()
  floorMesh.geometry = new THREE.PlaneGeometry(size, size)
  floorMesh.position.set(centerX, 0, centerZ)

  if (gridHelper) {
    scene.remove(gridHelper)
    gridHelper.dispose()
  }
  gridHelper = new THREE.GridHelper(size, Math.round(size))
  gridHelper.position.set(centerX, 0.01, centerZ)
  scene.add(gridHelper)
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

// 'orbit' = mouse-only (drag to rotate, scroll to zoom, right-click to pan)
// 'walk'  = WASD/arrow-key + Space/Shift free movement also active.
// Mouse orbit stays available in both modes - only whether keyboard input
// actually moves the camera is gated here.
const mode = ref<'orbit' | 'walk'>('orbit')

function toggleMode() {
  mode.value = mode.value === 'orbit' ? 'walk' : 'orbit'
}

function animate() {
  animationFrameId = requestAnimationFrame(animate)

  const delta = clock.getDelta()
  if (mode.value === 'walk') {
    walkControls.update(delta)
  }
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

  renderer = new THREE.WebGLRenderer({
    antialias: true,
  })

  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)

  containerRef.value.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.enablePan = true
  controls.minPolarAngle = 0
  controls.maxPolarAngle = Math.PI
  controls.minDistance = 0.5
  controls.maxDistance = 500

  walkControls = useWalkControls(camera, controls, { moveSpeed: 4 })

  createFloor()
  createGrid()
  createLights()
  renderWalls(props.floorPlan)
  fitGroundToPlan(props.floorPlan)
  frameCameraToPlan(props.floorPlan)

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
    fitGroundToPlan(newFloorPlan)
    frameCameraToPlan(newFloorPlan)
  },
  { deep: true },
)

onUnmounted(() => {
  cancelAnimationFrame(animationFrameId)
  window.removeEventListener('resize', handleResize)

  clearWalls()
  floorMesh?.geometry.dispose()
  floorMaterial.dispose()
  gridHelper?.dispose()

  walkControls?.dispose()
  controls?.dispose()
  renderer?.dispose()
})
</script>

<template>
  <div ref="containerRef" class="three-viewer">
    <button class="mode-toggle" @click="toggleMode">
      {{ mode === 'orbit' ? '🖱 Orbit mode' : '🚶 Walk mode' }}
    </button>
    <p v-if="mode === 'walk'" class="mode-hint">WASD to move · Space/Shift for up/down</p>
  </div>
</template>

<style scoped>
.three-viewer {
  position: relative;
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.mode-toggle {
  position: absolute;
  bottom: 16px;
  right: 16px;
  z-index: 10;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid #444;
  background: rgba(28, 28, 30, 0.85);
  color: #e5e5e5;
  font-size: 13px;
  cursor: pointer;
  backdrop-filter: blur(4px);
}

.mode-toggle:hover {
  border-color: #6b8afd;
}

.mode-hint {
  position: absolute;
  bottom: 54px;
  right: 16px;
  z-index: 10;
  margin: 0;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(28, 28, 30, 0.85);
  color: #999;
  font-size: 12px;
  white-space: nowrap;
}
</style>