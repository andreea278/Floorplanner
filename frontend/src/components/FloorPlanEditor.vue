<script setup lang="ts">
import { ref, computed } from 'vue'
import type { FloorPlan, Wall, Point2D } from '@/types/floorPlan'

const props = defineProps<{ floorPlan: FloorPlan }>()

const emit = defineEmits<{
  confirm: [floorPlan: FloorPlan]
}>()

// Local editable copy - we never mutate the prop directly (Vue best
// practice: props flow one way, down). All edits happen here; the parent
// only finds out when the user explicitly clicks "Generate 3D Model".
//
// Note: props.floorPlan is wrapped in a Vue reactive Proxy, and
// structuredClone() throws DataCloneError on that - so we use a JSON
// round-trip instead, which is safe here since Wall data is plain
// numbers/strings with no functions or special types.
const walls = ref<Wall[]>(JSON.parse(JSON.stringify(props.floorPlan.walls)))

// --- Display scale: plan units (meters) -> SVG coordinate space ---
// These are the SVG's own internal coordinates (the viewBox), separate
// from how many actual screen pixels it's displayed at - that separation
// is what makes zoom possible below.
const PX_PER_UNIT = 60
const PADDING = 40

const bounds = computed(() => {
  const xs = walls.value.flatMap((w) => [w.start.x, w.end.x])
  const ys = walls.value.flatMap((w) => [w.start.y, w.end.y])
  const minX = Math.min(...xs, 0)
  const minY = Math.min(...ys, 0)
  const maxX = Math.max(...xs, 1)
  const maxY = Math.max(...ys, 1)
  return { minX, minY, maxX, maxY }
})

const canvasWidth = computed(
  () => (bounds.value.maxX - bounds.value.minX) * PX_PER_UNIT + PADDING * 2,
)
const canvasHeight = computed(
  () => (bounds.value.maxY - bounds.value.minY) * PX_PER_UNIT + PADDING * 2,
)

function toScreen(point: Point2D) {
  return {
    x: (point.x - bounds.value.minX) * PX_PER_UNIT + PADDING,
    y: (point.y - bounds.value.minY) * PX_PER_UNIT + PADDING,
  }
}

function toPlanUnits(screenX: number, screenY: number): Point2D {
  return {
    x: (screenX - PADDING) / PX_PER_UNIT + bounds.value.minX,
    y: (screenY - PADDING) / PX_PER_UNIT + bounds.value.minY,
  }
}

// --- Zoom ---
// The SVG's *internal* coordinate system (viewBox) never changes - only
// how many actual screen pixels that viewBox is displayed across. This
// means all the plan-unit math above stays untouched; zoom only affects
// the `width`/`height` attributes, and we correct for it when reading
// pointer positions back out (see toSvgSpace below).
const zoom = ref(1)
const MIN_ZOOM = 0.3
const MAX_ZOOM = 3

function zoomIn() {
  zoom.value = Math.min(MAX_ZOOM, +(zoom.value + 0.25).toFixed(2))
}
function zoomOut() {
  zoom.value = Math.max(MIN_ZOOM, +(zoom.value - 0.25).toFixed(2))
}
function zoomReset() {
  zoom.value = 1
}

function onWheel(event: WheelEvent) {
  // Ctrl/Cmd + scroll = zoom (matches the trackpad-pinch gesture browsers
  // translate into a ctrlKey wheel event). Plain scroll still pans via the
  // wrapper's native overflow scrolling - we don't intercept that.
  if (!event.ctrlKey && !event.metaKey) return
  event.preventDefault()
  if (event.deltaY < 0) zoomIn()
  else zoomOut()
}

// Convert a raw pointer event into the SVG's internal coordinate space,
// accounting for both the CSS zoom and the wrapper's scroll offset.
function toSvgSpace(event: PointerEvent | MouseEvent): { x: number; y: number } {
  const rect = svgRef.value!.getBoundingClientRect()
  const scaleX = canvasWidth.value / rect.width
  const scaleY = canvasHeight.value / rect.height
  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  }
}

// --- Selection ---
const selectedWallId = ref<string | null>(null)

function selectWall(id: string) {
  selectedWallId.value = selectedWallId.value === id ? null : id
}

function deleteSelected() {
  if (!selectedWallId.value) return
  walls.value = walls.value.filter((w) => w.id !== selectedWallId.value)
  selectedWallId.value = null
}

// --- Dragging an endpoint ---
const dragging = ref<{ wallId: string; end: 'start' | 'end' } | null>(null)
const svgRef = ref<SVGSVGElement | null>(null)

function startDrag(event: PointerEvent, wallId: string, end: 'start' | 'end') {
  dragging.value = { wallId, end }
  // Pointer capture keeps sending pointermove/pointerup events to this
  // element even if the cursor moves faster than the handle can visually
  // keep up and briefly leaves it - without this, fast drags feel "sticky"
  // or drop the drag entirely, especially noticeable on a trackpad.
  ;(event.target as Element).setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return

  const svgPoint = toSvgSpace(event)
  const planPoint = toPlanUnits(svgPoint.x, svgPoint.y)

  const wall = walls.value.find((w) => w.id === dragging.value!.wallId)
  if (!wall) return

  wall[dragging.value.end] = planPoint
}

function stopDrag() {
  dragging.value = null
}

// --- Adding a new wall: click two points on empty canvas ---
const isAddingWall = ref(false)
const pendingStart = ref<Point2D | null>(null)

function onCanvasClick(event: MouseEvent) {
  if (!isAddingWall.value) return

  const svgPoint = toSvgSpace(event)
  const planPoint = toPlanUnits(svgPoint.x, svgPoint.y)

  if (!pendingStart.value) {
    pendingStart.value = planPoint
    return
  }

  walls.value.push({
    id: `wall-${crypto.randomUUID().slice(0, 8)}`,
    start: pendingStart.value,
    end: planPoint,
    height: 2.7,
    thickness: 0.2,
  })

  pendingStart.value = null
  isAddingWall.value = false
}

function toggleAddWall() {
  isAddingWall.value = !isAddingWall.value
  pendingStart.value = null
}

function confirmAndContinue() {
  emit('confirm', { ...props.floorPlan, walls: walls.value })
}
</script>

<template>
  <div class="editor">
    <div class="toolbar">
      <p class="hint">
        Drag the white dots to fix a wall's position. Click a wall to select
        it (turns red), then delete if it shouldn't be there. Ctrl/Cmd +
        scroll, or the buttons below, to zoom.
      </p>
      <div class="actions">
        <button
          class="tool-button"
          :class="{ active: isAddingWall }"
          @click="toggleAddWall"
        >
          {{ isAddingWall ? 'Click two points…' : '+ Add wall' }}
        </button>
        <button
          class="tool-button danger"
          :disabled="!selectedWallId"
          @click="deleteSelected"
        >
          Delete selected
        </button>
        <span class="divider" />
        <button class="tool-button" @click="zoomOut">−</button>
        <button class="tool-button zoom-label" @click="zoomReset">
          {{ Math.round(zoom * 100) }}%
        </button>
        <button class="tool-button" @click="zoomIn">+</button>
      </div>
    </div>

    <div class="canvas-wrapper" @wheel="onWheel">
      <svg
        ref="svgRef"
        :width="canvasWidth * zoom"
        :height="canvasHeight * zoom"
        :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`"
        class="canvas"
        :class="{ 'add-mode': isAddingWall }"
        @pointermove="onPointerMove"
        @pointerup="stopDrag"
        @pointercancel="stopDrag"
        @click="onCanvasClick"
      >
        <line
          v-for="wall in walls"
          :key="wall.id"
          :x1="toScreen(wall.start).x"
          :y1="toScreen(wall.start).y"
          :x2="toScreen(wall.end).x"
          :y2="toScreen(wall.end).y"
          :class="['wall-line', { selected: wall.id === selectedWallId }]"
          @click.stop="selectWall(wall.id)"
        />

        <template v-for="wall in walls" :key="wall.id + '-handles'">
          <circle
            :cx="toScreen(wall.start).x"
            :cy="toScreen(wall.start).y"
            r="9"
            class="handle"
            @pointerdown.stop="(e) => startDrag(e, wall.id, 'start')"
          />
          <circle
            :cx="toScreen(wall.end).x"
            :cy="toScreen(wall.end).y"
            r="9"
            class="handle"
            @pointerdown.stop="(e) => startDrag(e, wall.id, 'end')"
          />
        </template>

        <circle
          v-if="pendingStart"
          :cx="toScreen(pendingStart).x"
          :cy="toScreen(pendingStart).y"
          r="6"
          class="pending-point"
        />
      </svg>
    </div>

    <button class="continue-button" @click="confirmAndContinue">
      Generate 3D Model →
    </button>
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 24px;
  color: #e5e5e5;
  max-height: 100vh;
  box-sizing: border-box;
}

.toolbar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: 560px;
  text-align: center;
}

.hint {
  font-size: 13px;
  color: #999;
  margin: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.divider {
  width: 1px;
  height: 20px;
  background: #333;
  margin: 0 4px;
}

.tool-button {
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1e;
  color: #e5e5e5;
  font-size: 13px;
  cursor: pointer;
}

.tool-button:hover:not(:disabled) {
  border-color: #6b8afd;
}

.tool-button.active {
  border-color: #6b8afd;
  background: #22242e;
}

.tool-button.zoom-label {
  min-width: 52px;
  cursor: default;
}

.tool-button.danger:not(:disabled):hover {
  border-color: #ff6b6b;
}

.tool-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.canvas-wrapper {
  max-width: 90vw;
  max-height: 60vh;
  overflow: auto;
  background: #16161a;
  border: 1px solid #2a2a2e;
  border-radius: 8px;
}

.canvas {
  display: block;
  touch-action: none;
}

.canvas.add-mode {
  cursor: crosshair;
}

.wall-line {
  stroke: #6b8afd;
  stroke-width: 4;
  cursor: pointer;
}

.wall-line.selected {
  stroke: #ff6b6b;
}

.handle {
  fill: #e5e5e5;
  stroke: #6b8afd;
  stroke-width: 2;
  cursor: grab;
  touch-action: none;
}

.handle:hover {
  fill: #6b8afd;
  stroke: #e5e5e5;
}

.pending-point {
  fill: #ffd166;
}

.continue-button {
  padding: 10px 20px;
  border-radius: 8px;
  border: none;
  background: #6b8afd;
  color: #0d0d0f;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  flex-shrink: 0;
}

.continue-button:hover {
  background: #82a0ff;
}
</style>