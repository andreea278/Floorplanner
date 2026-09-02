<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { useWalkControls } from '@/composables/useWalkControls'
import { useUndoStack } from '@/composables/useUndoStack'
import type { FloorPlan, Wall, Door, Window, FurnitureItem, FurnitureKind } from '@/types/floorPlan'

const props = defineProps<{
  floorPlan: FloorPlan
}>()

const emit = defineEmits<{
  update: [floorPlan: FloorPlan]
}>()

const containerRef = ref<HTMLDivElement | null>(null)

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: OrbitControls
let walkControls: ReturnType<typeof useWalkControls>
let animationFrameId = 0

const clock = new THREE.Clock()

const walls = ref<Wall[]>(JSON.parse(JSON.stringify(props.floorPlan.walls)))
const doors = ref<Door[]>(JSON.parse(JSON.stringify(props.floorPlan.doors ?? [])))
const windows = ref<Window[]>(JSON.parse(JSON.stringify(props.floorPlan.windows ?? [])))
const furniture = ref<FurnitureItem[]>(JSON.parse(JSON.stringify(props.floorPlan.furniture ?? [])))
let suppressNextWatchReframe = false

function wallById(id: string): Wall | undefined {
  return walls.value.find((w) => w.id === id)
}

function currentPlan(): FloorPlan {
  return {
    ...props.floorPlan,
    walls: walls.value,
    doors: doors.value,
    windows: windows.value,
    furniture: furniture.value,
  }
}

// --- Undo ---
interface Snapshot {
  walls: Wall[]
  doors: Door[]
  windows: Window[]
  furniture: FurnitureItem[]
}
const undoStack = useUndoStack<Snapshot>()

function pushUndoSnapshot() {
  undoStack.push({
    walls: JSON.parse(JSON.stringify(walls.value)),
    doors: JSON.parse(JSON.stringify(doors.value)),
    windows: JSON.parse(JSON.stringify(windows.value)),
    furniture: JSON.parse(JSON.stringify(furniture.value)),
  })
}

function undo() {
  const snapshot = undoStack.undo()
  if (!snapshot) return
  walls.value = snapshot.walls
  doors.value = snapshot.doors
  windows.value = snapshot.windows
  furniture.value = snapshot.furniture
  selectedFurnitureId.value = null
  selectedWallId.value = null
  rebuildAndEmit()
}

const wallMaterial = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.6 })
const glassMaterial = new THREE.MeshStandardMaterial({
  color: 0xbcd8ff,
  roughness: 0.1,
  metalness: 0.1,
  transparent: true,
  opacity: 0.35,
})

const wallGroups: THREE.Group[] = []
const wallHitMeshes: THREE.Mesh[] = []

function buildWallGroup(wall: Wall, wallDoors: Door[], wallWindows: Window[]): THREE.Group {
  const group = new THREE.Group()
  group.userData = { wallId: wall.id }

  const dx = wall.end.x - wall.start.x
  const dz = wall.end.y - wall.start.y
  const length = Math.hypot(dx, dz)
  const angle = Math.atan2(dz, dx)

  group.position.set((wall.start.x + wall.end.x) / 2, 0, (wall.start.y + wall.end.y) / 2)
  group.rotation.y = -angle

  type Opening = (Door & { kind: 'door' }) | (Window & { kind: 'window' })
  const openings: Opening[] = [
    ...wallDoors.filter((d) => d.wallId === wall.id).map((d) => ({ ...d, kind: 'door' as const })),
    ...wallWindows.filter((w) => w.wallId === wall.id).map((w) => ({ ...w, kind: 'window' as const })),
  ].sort((a, b) => a.offset - b.offset)

  let cursor = -length / 2
  const wallMat = wall.color
    ? new THREE.MeshStandardMaterial({ color: wall.color, roughness: 0.6 })
    : wallMaterial

  function addSeg(localXStart: number, localXEnd: number, yStart: number, yEnd: number) {
    const segLength = localXEnd - localXStart
    const segHeight = yEnd - yStart
    if (segLength <= 0.001 || segHeight <= 0.001) return
    const geometry = new THREE.BoxGeometry(segLength, segHeight, wall.thickness)
    const mesh = new THREE.Mesh(geometry, wallMat)
    mesh.position.set((localXStart + localXEnd) / 2, (yStart + yEnd) / 2, 0)
    mesh.userData = { wallId: wall.id, ownedMaterial: !!wall.color }
    group.add(mesh)
  }

  for (const opening of openings) {
    const halfWidth = opening.width / 2
    const openStart = Math.max(opening.offset - halfWidth - length / 2, -length / 2)
    const openEnd = Math.min(opening.offset + halfWidth - length / 2, length / 2)
    if (openEnd <= openStart) continue

    addSeg(cursor, openStart, 0, wall.height)

    if (opening.kind === 'door') {
      addSeg(openStart, openEnd, opening.height, wall.height)
    } else {
      addSeg(openStart, openEnd, 0, opening.sillHeight)
      addSeg(openStart, openEnd, opening.sillHeight + opening.height, wall.height)

      const paneGeometry = new THREE.BoxGeometry(
        openEnd - openStart,
        opening.height,
        Math.max(wall.thickness * 0.3, 0.02),
      )
      const pane = new THREE.Mesh(paneGeometry, glassMaterial)
      pane.position.set((openStart + openEnd) / 2, opening.sillHeight + opening.height / 2, 0)
      group.add(pane)
    }

    cursor = openEnd
  }

  addSeg(cursor, length / 2, 0, wall.height)

  return group
}

function disposeGroup(group: THREE.Group) {
  group.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.geometry.dispose()
      if (child.userData.ownedMaterial) {
        ;(child.material as THREE.Material).dispose()
      }
    }
  })
}

function clearWalls() {
  for (const group of wallGroups) {
    scene.remove(group)
    disposeGroup(group)
  }
  wallGroups.length = 0
  wallHitMeshes.length = 0
}

function renderWalls(floorPlan: FloorPlan) {
  clearWalls()

  for (const wall of floorPlan.walls) {
    const group = buildWallGroup(wall, floorPlan.doors ?? [], floorPlan.windows ?? [])
    wallGroups.push(group)
    scene.add(group)
    group.traverse((child) => {
      if (child instanceof THREE.Mesh && child.userData.wallId) {
        wallHitMeshes.push(child)
      }
    })
  }
}

// --- Furniture ---
const FURNITURE_DIMENSIONS: Record<FurnitureKind, { w: number; d: number; h: number }> = {
  sofa: { w: 2.0, d: 0.9, h: 0.85 },
  bed: { w: 1.6, d: 2.0, h: 0.55 },
  table: { w: 1.4, d: 0.8, h: 0.75 },
  chair: { w: 0.45, d: 0.45, h: 0.85 },
  toilet: { w: 0.4, d: 0.65, h: 0.4 },
  sink: { w: 0.6, d: 0.45, h: 0.85 },
  bathtub: { w: 1.7, d: 0.75, h: 0.55 },
  stove: { w: 0.6, d: 0.6, h: 0.85 },
  fridge: { w: 0.7, d: 0.7, h: 1.8 },
}

const furnitureMaterials: Record<FurnitureKind, THREE.MeshStandardMaterial> = {
  sofa: new THREE.MeshStandardMaterial({ color: 0x8899cc, roughness: 0.85 }),
  bed: new THREE.MeshStandardMaterial({ color: 0xe8d5b7, roughness: 0.9 }),
  table: new THREE.MeshStandardMaterial({ color: 0x8b5a2b, roughness: 0.6 }),
  chair: new THREE.MeshStandardMaterial({ color: 0x555555, roughness: 0.7 }),
  toilet: new THREE.MeshStandardMaterial({ color: 0xf5f5f5, roughness: 0.25 }),
  sink: new THREE.MeshStandardMaterial({ color: 0xf5f5f5, roughness: 0.25 }),
  bathtub: new THREE.MeshStandardMaterial({ color: 0xf5f5f5, roughness: 0.25 }),
  stove: new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.35, metalness: 0.3 }),
  fridge: new THREE.MeshStandardMaterial({ color: 0xdddddd, roughness: 0.35, metalness: 0.3 }),
}

const furnitureGroups: THREE.Group[] = []

function buildFurnitureMesh(item: FurnitureItem): THREE.Group {
  const group = new THREE.Group()
  const dim = FURNITURE_DIMENSIONS[item.kind]
  const baseMaterial = furnitureMaterials[item.kind]
  const material = item.color
    ? new THREE.MeshStandardMaterial({
        color: item.color,
        roughness: baseMaterial.roughness,
        metalness: baseMaterial.metalness,
      })
    : baseMaterial
  const isOwnedMaterial = !!item.color

  function addBox(w: number, h: number, d: number, x: number, y: number, z: number) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material)
    mesh.position.set(x, y, z)
    mesh.userData = { kind: 'furniture', furnitureId: item.id, ownedMaterial: isOwnedMaterial }
    group.add(mesh)
  }

  if (item.kind === 'sofa') {
    addBox(dim.w, dim.h * 0.55, dim.d, 0, dim.h * 0.275, 0)
    addBox(dim.w, dim.h * 0.45, dim.d * 0.2, 0, dim.h * 0.55 + dim.h * 0.225, -dim.d / 2 + dim.d * 0.1)
  } else if (item.kind === 'bed') {
    addBox(dim.w, dim.h, dim.d, 0, dim.h / 2, 0)
    addBox(dim.w, dim.h * 1.6, 0.08, 0, dim.h * 0.8, -dim.d / 2 + 0.04)
  } else if (item.kind === 'table') {
    addBox(dim.w, 0.05, dim.d, 0, dim.h - 0.025, 0)
    const legOffsets: Array<[number, number]> = [
      [dim.w / 2 - 0.05, dim.d / 2 - 0.05],
      [-(dim.w / 2 - 0.05), dim.d / 2 - 0.05],
      [dim.w / 2 - 0.05, -(dim.d / 2 - 0.05)],
      [-(dim.w / 2 - 0.05), -(dim.d / 2 - 0.05)],
    ]
    for (const [lx, lz] of legOffsets) {
      addBox(0.05, dim.h - 0.05, 0.05, lx, (dim.h - 0.05) / 2, lz)
    }
  } else if (item.kind === 'chair') {
    addBox(dim.w, 0.05, dim.d, 0, dim.h * 0.5, 0)
    addBox(dim.w, dim.h * 0.5, 0.05, 0, dim.h * 0.75, -dim.d / 2 + 0.025)
    const legOffsets: Array<[number, number]> = [
      [dim.w / 2 - 0.03, dim.d / 2 - 0.03],
      [-(dim.w / 2 - 0.03), dim.d / 2 - 0.03],
      [dim.w / 2 - 0.03, -(dim.d / 2 - 0.03)],
      [-(dim.w / 2 - 0.03), -(dim.d / 2 - 0.03)],
    ]
    for (const [lx, lz] of legOffsets) {
      addBox(0.03, dim.h * 0.5, 0.03, lx, dim.h * 0.25, lz)
    }
  } else if (item.kind === 'toilet') {
    addBox(dim.w, dim.h * 0.35, dim.d * 0.7, 0, dim.h * 0.175, dim.d * 0.15)
    addBox(dim.w * 0.9, dim.h * 0.55, dim.d * 0.25, 0, dim.h * 0.35 + dim.h * 0.275, -dim.d / 2 + dim.d * 0.1)
  } else if (item.kind === 'sink') {
    addBox(dim.w, dim.h * 0.05, dim.d, 0, dim.h * 0.95, 0)
    addBox(dim.w * 0.7, dim.h * 0.9, dim.d * 0.7, 0, dim.h * 0.45, 0)
  } else if (item.kind === 'bathtub') {
    addBox(dim.w, dim.h, dim.d, 0, dim.h / 2, 0)
    addBox(dim.w * 0.85, dim.h * 0.6, dim.d * 0.65, 0, dim.h * 0.6 + dim.h * 0.3, 0)
  } else if (item.kind === 'stove') {
    addBox(dim.w, dim.h, dim.d, 0, dim.h / 2, 0)
    addBox(dim.w * 0.95, 0.03, dim.d * 0.95, 0, dim.h + 0.015, 0)
  } else {
    addBox(dim.w, dim.h, dim.d, 0, dim.h / 2, 0)
    addBox(dim.w * 0.02, dim.h * 0.5, 0.03, dim.w / 2 - 0.02, dim.h * 0.6, dim.d / 2 - 0.05)
  }

  group.position.set(item.x, 0, item.y)
  group.rotation.y = item.rotation
  group.userData = { kind: 'furniture', furnitureId: item.id }
  return group
}

function clearFurniture() {
  for (const group of furnitureGroups) {
    scene.remove(group)
    group.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose()
        if (child.userData.ownedMaterial) {
          ;(child.material as THREE.Material).dispose()
        }
      }
    })
  }
  furnitureGroups.length = 0
}

function renderFurniture() {
  clearFurniture()
  for (const item of furniture.value) {
    const group = buildFurnitureMesh(item)
    furnitureGroups.push(group)
    scene.add(group)
  }
  updateSelectionHelper()
}

// --- Selection: either a furniture piece OR a wall ---
const selectedFurnitureId = ref<string | null>(null)
const selectedWallId = ref<string | null>(null)
const DEFAULT_FURNITURE_COLOR = '#ffffff'
const furnitureColorPicker = ref(DEFAULT_FURNITURE_COLOR)
const wallColorPicker = ref('#ffffff')
let selectionHelper: THREE.BoxHelper | null = null

function updateSelectionHelper() {
  if (selectionHelper) {
    scene.remove(selectionHelper)
    selectionHelper = null
  }
  if (selectedFurnitureId.value) {
    const group = furnitureGroups.find((g) => g.userData.furnitureId === selectedFurnitureId.value)
    if (group) selectionHelper = new THREE.BoxHelper(group, 0xffd166)
  } else if (selectedWallId.value) {
    const group = wallGroups.find((g) => g.userData.wallId === selectedWallId.value)
    if (group) selectionHelper = new THREE.BoxHelper(group, 0xffd166)
  }
  if (selectionHelper) scene.add(selectionHelper)
}

watch(selectedFurnitureId, (id) => {
  if (!id) return
  const item = furniture.value.find((f) => f.id === id)
  if (!item) return
  furnitureColorPicker.value = item.color ?? `#${furnitureMaterials[item.kind].color.getHexString()}`
})

watch(selectedWallId, (id) => {
  if (!id) return
  const wall = wallById(id)
  wallColorPicker.value = wall?.color ?? '#ffffff'
})

function applyFurnitureColor() {
  if (!selectedFurnitureId.value) return
  pushUndoSnapshot()
  const item = furniture.value.find((f) => f.id === selectedFurnitureId.value)
  if (!item) return
  item.color = furnitureColorPicker.value
  rebuildAndEmit()
}

function applyWallColor() {
  if (!selectedWallId.value) return
  pushUndoSnapshot()
  const wall = wallById(selectedWallId.value)
  if (!wall) return
  wall.color = wallColorPicker.value
  rebuildAndEmit()
}

function rotateSelected(deltaRad: number) {
  if (!selectedFurnitureId.value) return
  pushUndoSnapshot()
  const item = furniture.value.find((f) => f.id === selectedFurnitureId.value)
  if (!item) return
  item.rotation += deltaRad
  rebuildAndEmit()
}

// --- 3D edit mode ---
type EditMode = 'door' | 'window' | FurnitureKind | null
const editMode = ref<EditMode>(null)

function toggleEditMode(editModeKind: Exclude<EditMode, null>) {
  editMode.value = editMode.value === editModeKind ? null : editModeKind
  selectedFurnitureId.value = null
  selectedWallId.value = null
  updateSelectionHelper()
}

function rebuildAndEmit() {
  renderWalls(currentPlan())
  renderFurniture()
  suppressNextWatchReframe = true
  emit('update', currentPlan())
}

function addOpening3D(kind: 'door' | 'window', wall: Wall, rawOffset: number, wallLength: number) {
  pushUndoSnapshot()

  const defaultWidth = kind === 'door' ? 0.9 : 1.2
  const halfWidth = Math.min(defaultWidth / 2, Math.max(wallLength / 2 - 0.01, 0))
  const offset = Math.min(Math.max(rawOffset, halfWidth), Math.max(halfWidth, wallLength - halfWidth))

  if (kind === 'door') {
    doors.value.push({
      id: `door-${crypto.randomUUID().slice(0, 8)}`,
      wallId: wall.id,
      offset,
      width: defaultWidth,
      height: 2.1,
    })
  } else {
    windows.value.push({
      id: `window-${crypto.randomUUID().slice(0, 8)}`,
      wallId: wall.id,
      offset,
      width: defaultWidth,
      height: 1.2,
      sillHeight: 0.9,
    })
  }

  editMode.value = null
  rebuildAndEmit()
}

function addFurniture3D(kind: FurnitureKind, x: number, z: number) {
  pushUndoSnapshot()

  furniture.value.push({
    id: `furniture-${crypto.randomUUID().slice(0, 8)}`,
    kind,
    x,
    y: z,
    rotation: 0,
  })
  editMode.value = null
  rebuildAndEmit()
}

function deleteSelectedFurniture() {
  if (!selectedFurnitureId.value) return
  pushUndoSnapshot()
  furniture.value = furniture.value.filter((f) => f.id !== selectedFurnitureId.value)
  selectedFurnitureId.value = null
  rebuildAndEmit()
}

function furnitureMeshesFlat(): THREE.Object3D[] {
  const all: THREE.Object3D[] = []
  for (const g of furnitureGroups) g.traverse((c) => all.push(c))
  return all
}

// --- First-person look: hold the mouse button down and drag to rotate the
// camera in place (pure yaw/pitch, no orbit target/radius) - no special
// "click to engage" gate, no Pointer Lock, no Esc needed to leave it.
// Releasing the button simply stops rotating, same as letting go of the
// wheel in a car. Only active in walk mode - orbit mode keeps its normal
// OrbitControls drag-to-orbit behavior untouched. ---
const LOOK_SENSITIVITY = 0.0035
const MIN_PITCH = -Math.PI / 2 + 0.05
const MAX_PITCH = Math.PI / 2 - 0.05
let yaw = 0
let pitch = 0
let isLookDragging = false
let lastLookPos: { x: number; y: number } | null = null

function syncYawPitchFromCamera() {
  const euler = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ')
  yaw = euler.y
  pitch = euler.x
}

function applyLookDelta(dx: number, dy: number) {
  yaw -= dx * LOOK_SENSITIVITY
  pitch -= dy * LOOK_SENSITIVITY
  pitch = Math.min(MAX_PITCH, Math.max(MIN_PITCH, pitch))
  camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'))
}

// --- Raycasting + click-vs-drag for placing/selecting things. The cursor
// is always visible now (no Pointer Lock), so aiming just uses the real
// cursor position. ---
const raycaster = new THREE.Raycaster()
let pointerDownPos: { x: number; y: number } | null = null
let draggingFurnitureId: string | null = null
const CLICK_MOVE_THRESHOLD = 6

function computeRaycastNdc(event: PointerEvent): THREE.Vector2 {
  const rect = renderer.domElement.getBoundingClientRect()
  return new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 + 1,
  )
}

function onDomPointerDown(event: PointerEvent) {
  pointerDownPos = { x: event.clientX, y: event.clientY }

  // Dragging the ALREADY-selected furniture piece moves it - this check
  // takes priority over starting a look-drag.
  if (!editMode.value && selectedFurnitureId.value) {
    raycaster.setFromCamera(computeRaycastNdc(event), camera)
    const hits = raycaster.intersectObjects(furnitureMeshesFlat(), false)
    if (hits.length > 0 && hits[0]!.object.userData.furnitureId === selectedFurnitureId.value) {
      pushUndoSnapshot()
      draggingFurnitureId = selectedFurnitureId.value
      controls.enabled = false
      ;(event.target as Element).setPointerCapture(event.pointerId)
      return
    }
  }

  if (mode.value === 'walk') {
    syncYawPitchFromCamera()
    isLookDragging = true
    lastLookPos = { x: event.clientX, y: event.clientY }
    ;(event.target as Element).setPointerCapture(event.pointerId)
  }
}

function onDomPointerMove(event: PointerEvent) {
  if (draggingFurnitureId) {
    raycaster.setFromCamera(computeRaycastNdc(event), camera)
    const hits = raycaster.intersectObject(floorMesh, false)
    if (hits.length === 0) return
    const item = furniture.value.find((f) => f.id === draggingFurnitureId)
    if (!item) return
    item.x = hits[0]!.point.x
    item.y = hits[0]!.point.z
    renderFurniture()
    return
  }

  if (isLookDragging && lastLookPos) {
    applyLookDelta(event.clientX - lastLookPos.x, event.clientY - lastLookPos.y)
    lastLookPos = { x: event.clientX, y: event.clientY }
  }
}

function onDomPointerUp(event: PointerEvent) {
  if (draggingFurnitureId) {
    draggingFurnitureId = null
    controls.enabled = mode.value === 'orbit'
    pointerDownPos = null
    rebuildAndEmit()
    return
  }

  isLookDragging = false
  lastLookPos = null

  if (!pointerDownPos) return
  const moved = Math.hypot(event.clientX - pointerDownPos.x, event.clientY - pointerDownPos.y)
  pointerDownPos = null
  if (moved > CLICK_MOVE_THRESHOLD) return // was a look-drag, not a click
  handleEditClick(event)
}

function handleEditClick(event: PointerEvent) {
  if (!editMode.value) {
    trySelectItem(event)
    return
  }

  raycaster.setFromCamera(computeRaycastNdc(event), camera)

  if (editMode.value === 'door' || editMode.value === 'window') {
    const hits = raycaster.intersectObjects(wallHitMeshes, false)
    if (hits.length === 0) return
    const wallId = hits[0]!.object.userData.wallId as string
    const wall = wallById(wallId)
    if (!wall) return

    const dx = wall.end.x - wall.start.x
    const dz = wall.end.y - wall.start.y
    const length = Math.hypot(dx, dz)
    if (length < 1e-6) return
    const ux = dx / length
    const uz = dz / length
    const localX = hits[0]!.point.x - wall.start.x
    const localZ = hits[0]!.point.z - wall.start.y
    let t = localX * ux + localZ * uz
    t = Math.min(length, Math.max(0, t))

    addOpening3D(editMode.value, wall, t, length)
  } else {
    const hits = raycaster.intersectObject(floorMesh, false)
    if (hits.length === 0) return
    addFurniture3D(editMode.value, hits[0]!.point.x, hits[0]!.point.z)
  }
}

function trySelectItem(event: PointerEvent) {
  raycaster.setFromCamera(computeRaycastNdc(event), camera)

  const furnitureHits = raycaster.intersectObjects(furnitureMeshesFlat(), false)
  if (furnitureHits.length > 0) {
    selectedFurnitureId.value = furnitureHits[0]!.object.userData.furnitureId as string
    selectedWallId.value = null
    updateSelectionHelper()
    return
  }

  const wallHits = raycaster.intersectObjects(wallHitMeshes, false)
  if (wallHits.length > 0) {
    selectedWallId.value = wallHits[0]!.object.userData.wallId as string
    selectedFurnitureId.value = null
    updateSelectionHelper()
    return
  }

  selectedFurnitureId.value = null
  selectedWallId.value = null
  updateSelectionHelper()
}

function onKeyDown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    undo()
    return
  }
  if ((event.key === 'Delete' || event.key === 'Backspace') && selectedFurnitureId.value) {
    event.preventDefault()
    deleteSelectedFurniture()
  } else if (event.key === 'Escape') {
    editMode.value = null
    selectedFurnitureId.value = null
    selectedWallId.value = null
    updateSelectionHelper()
  }
}

// --- Camera framing ---
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
  camera.lookAt(controls.target)
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

const mode = ref<'orbit' | 'walk'>('orbit')

function toggleMode() {
  if (mode.value === 'orbit') {
    mode.value = 'walk'
    controls.enabled = false
    syncYawPitchFromCamera()
  } else {
    mode.value = 'orbit'
    const forward = new THREE.Vector3()
    camera.getWorldDirection(forward)
    controls.target.copy(camera.position).addScaledVector(forward, 5)
    controls.enabled = true
    controls.update()
  }
}

function animate() {
  animationFrameId = requestAnimationFrame(animate)

  const delta = clock.getDelta()
  if (mode.value === 'walk') {
    walkControls.update(delta)
  } else {
    controls.update()
  }
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
  controls.rotateSpeed = 0.4

  walkControls = useWalkControls(camera, { moveSpeed: 4 })

  createFloor()
  createGrid()
  createLights()
  renderWalls(currentPlan())
  renderFurniture()
  fitGroundToPlan(currentPlan())
  frameCameraToPlan(currentPlan())

  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', onKeyDown)
  renderer.domElement.addEventListener('pointerdown', onDomPointerDown)
  renderer.domElement.addEventListener('pointermove', onDomPointerMove)
  renderer.domElement.addEventListener('pointerup', onDomPointerUp)

  animate()
})

watch(
  () => props.floorPlan,
  (newFloorPlan) => {
    if (!scene) {
      return
    }

    walls.value = JSON.parse(JSON.stringify(newFloorPlan.walls))
    doors.value = JSON.parse(JSON.stringify(newFloorPlan.doors ?? []))
    windows.value = JSON.parse(JSON.stringify(newFloorPlan.windows ?? []))
    furniture.value = JSON.parse(JSON.stringify(newFloorPlan.furniture ?? []))

    renderWalls(currentPlan())
    renderFurniture()

    if (suppressNextWatchReframe) {
      suppressNextWatchReframe = false
    } else {
      fitGroundToPlan(currentPlan())
      frameCameraToPlan(currentPlan())
    }
  },
  { deep: true },
)

onUnmounted(() => {
  cancelAnimationFrame(animationFrameId)
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', onKeyDown)
  renderer.domElement.removeEventListener('pointerdown', onDomPointerDown)
  renderer.domElement.removeEventListener('pointermove', onDomPointerMove)
  renderer.domElement.removeEventListener('pointerup', onDomPointerUp)

  clearWalls()
  clearFurniture()
  wallMaterial.dispose()
  glassMaterial.dispose()
  Object.values(furnitureMaterials).forEach((m) => m.dispose())
  floorMesh?.geometry.dispose()
  floorMaterial.dispose()
  gridHelper?.dispose()

  walkControls?.dispose()
  controls?.dispose()
  renderer?.dispose()
})
</script>

<template>
  <div ref="containerRef" class="three-viewer" :class="{ 'walk-cursor': mode === 'walk' }">
    <div class="edit-toolbar">
      <button class="tool-button" :disabled="!undoStack.canUndo()" @click="undo">↶ Undo</button>
      <span class="edit-divider" />
      <button class="tool-button" :class="{ active: editMode === 'door' }" @click="toggleEditMode('door')">
        {{ editMode === 'door' ? 'Click a wall…' : '+ Door' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'window' }" @click="toggleEditMode('window')">
        {{ editMode === 'window' ? 'Click a wall…' : '+ Window' }}
      </button>

      <span class="edit-divider" />
      <button class="tool-button" :class="{ active: editMode === 'sofa' }" @click="toggleEditMode('sofa')">
        {{ editMode === 'sofa' ? 'Click the floor…' : '🛋 Sofa' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'bed' }" @click="toggleEditMode('bed')">
        {{ editMode === 'bed' ? 'Click the floor…' : '🛏 Bed' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'table' }" @click="toggleEditMode('table')">
        {{ editMode === 'table' ? 'Click the floor…' : '🍽 Table' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'chair' }" @click="toggleEditMode('chair')">
        {{ editMode === 'chair' ? 'Click the floor…' : '🪑 Chair' }}
      </button>

      <span class="edit-divider" />
      <button class="tool-button" :class="{ active: editMode === 'toilet' }" @click="toggleEditMode('toilet')">
        {{ editMode === 'toilet' ? 'Click the floor…' : '🚽 Toilet' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'sink' }" @click="toggleEditMode('sink')">
        {{ editMode === 'sink' ? 'Click the floor…' : '🚰 Sink' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'bathtub' }" @click="toggleEditMode('bathtub')">
        {{ editMode === 'bathtub' ? 'Click the floor…' : '🛁 Bathtub' }}
      </button>

      <span class="edit-divider" />
      <button class="tool-button" :class="{ active: editMode === 'stove' }" @click="toggleEditMode('stove')">
        {{ editMode === 'stove' ? 'Click the floor…' : '🍳 Stove' }}
      </button>
      <button class="tool-button" :class="{ active: editMode === 'fridge' }" @click="toggleEditMode('fridge')">
        {{ editMode === 'fridge' ? 'Click the floor…' : '❄️ Fridge' }}
      </button>

      <template v-if="selectedFurnitureId">
        <span class="edit-divider" />
        <span class="hint-inline">Drag to move · Delete to remove</span>
        <button class="tool-button" title="Rotate left" @click="rotateSelected(-Math.PI / 12)">⟲</button>
        <button class="tool-button" title="Rotate right" @click="rotateSelected(Math.PI / 12)">⟳</button>
        <input
          type="color"
          v-model="furnitureColorPicker"
          @change="applyFurnitureColor"
          class="color-input"
          title="Color"
        />
      </template>
      <template v-else-if="selectedWallId">
        <span class="edit-divider" />
        <span class="hint-inline">Wall selected</span>
        <input
          type="color"
          v-model="wallColorPicker"
          @change="applyWallColor"
          class="color-input"
          title="Wall color"
        />
      </template>
    </div>

    <button class="mode-toggle" @click="toggleMode">
      {{ mode === 'orbit' ? '🖱 Orbit mode' : '🚶 Walk mode' }}
    </button>
    <p v-if="mode === 'walk'" class="mode-hint">WASD to move · drag to look around · Space/Shift for up/down</p>
  </div>
</template>

<style scoped>
.three-viewer {
  position: relative;
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.three-viewer.walk-cursor {
  cursor: grab;
}

.three-viewer.walk-cursor:active {
  cursor: grabbing;
}

.edit-toolbar {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 72vw;
  padding: 6px;
  border-radius: 10px;
  background: rgba(28, 28, 30, 0.85);
  backdrop-filter: blur(4px);
}

.edit-divider {
  width: 1px;
  height: 20px;
  background: #444;
  margin: 0 2px;
}

.tool-button {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1e;
  color: #e5e5e5;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}

.tool-button:hover:not(:disabled) {
  border-color: #6b8afd;
}

.tool-button.active {
  border-color: #6b8afd;
  background: #22242e;
}

.tool-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.color-input {
  width: 30px;
  height: 26px;
  padding: 2px;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1e;
  cursor: pointer;
}

.hint-inline {
  font-size: 12px;
  color: #ffd166;
  padding: 0 4px;
  white-space: nowrap;
}

.mode-toggle {
  position: absolute;
  bottom: 16px;
  right: 16px;
  z-index: 20;
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
  z-index: 20;
  margin: 0;
  padding: 4px 10px;
  border-radius: 6px;
  background: rgba(28, 28, 30, 0.85);
  color: #999;
  font-size: 12px;
  white-space: nowrap;
}
</style>