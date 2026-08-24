<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { FloorPlan, Wall, Point2D } from '@/types/floorPlan'

const props = defineProps<{ floorPlan: FloorPlan }>()

const emit = defineEmits<{
  confirm: [floorPlan: FloorPlan]
}>()

// Local editable copy - we never mutate the prop directly (Vue best
// practice: props flow one way, down). All edits happen here; the parent
// only finds out when we emit 'confirm' (bottom CTA or the quick 3D-view
// toggle below both do this).
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
  // No walls yet (blank start) - give the user a comfortable 10x8m area to
  // draw on instead of a tiny 1x1 canvas.
  if (walls.value.length === 0) {
    return { minX: 0, minY: 0, maxX: 10, maxY: 8 }
  }

  const xs = walls.value.flatMap((w) => [w.start.x, w.end.x])
  const ys = walls.value.flatMap((w) => [w.start.y, w.end.y])
  return {
    minX: Math.min(...xs, 0),
    minY: Math.min(...ys, 0),
    maxX: Math.max(...xs, 1),
    maxY: Math.max(...ys, 1),
  }
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

// --- Snapping ---
// While adding or dragging a wall endpoint, if the point lands within this
// many plan units (meters) of an existing wall's corner, snap to that exact
// corner instead of the raw cursor position - so walls actually connect
// with no gap, instead of needing a pixel-perfect click.
const SNAP_DISTANCE = 0.35

function findSnapTarget(point: Point2D, excludeWallId?: string): Point2D | null {
  let closest: Point2D | null = null
  let closestDist = SNAP_DISTANCE

  for (const wall of walls.value) {
    if (wall.id === excludeWallId) continue
    for (const candidate of [wall.start, wall.end]) {
      const dist = Math.hypot(candidate.x - point.x, candidate.y - point.y)
      if (dist < closestDist) {
        closestDist = dist
        closest = candidate
      }
    }
  }

  return closest
}

// Live preview of the snap target while adding a wall, so the user can see
// which corner they're about to lock onto before clicking.
const snapPreview = ref<Point2D | null>(null)

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
// A Set of wall ids so several walls can be selected at once (shift/ctrl/
// cmd-click to toggle one in or out, or drag a marquee box over several).
const selectedWallIds = ref<Set<string>>(new Set())
const selectedCount = computed(() => selectedWallIds.value.size)

function isSelected(id: string): boolean {
  return selectedWallIds.value.has(id)
}

function selectWall(id: string, event: MouseEvent) {
  const additive = event.shiftKey || event.metaKey || event.ctrlKey
  const next = new Set(selectedWallIds.value)

  if (additive) {
    if (next.has(id)) next.delete(id)
    else next.add(id)
  } else {
    next.clear()
    next.add(id)
  }

  selectedWallIds.value = next
}

function selectAll() {
  selectedWallIds.value = new Set(walls.value.map((w) => w.id))
}

function clearSelection() {
  selectedWallIds.value = new Set()
}

function deleteSelected() {
  if (selectedWallIds.value.size === 0) return
  walls.value = walls.value.filter((w) => !selectedWallIds.value.has(w.id))
  clearSelection()
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

function stopDrag() {
  dragging.value = null
}

// --- Marquee (rubber-band) selection ---
// Dragging on empty canvas draws a selection box; any wall whose bounding
// box overlaps it gets added to the selection on release.
const marqueeStart = ref<{ x: number; y: number } | null>(null)
const marqueeCurrent = ref<{ x: number; y: number } | null>(null)
const isMarqueeSelecting = ref(false)

function wallIntersectsRect(
  wall: Wall,
  rect: { minX: number; maxX: number; minY: number; maxY: number },
): boolean {
  const p1 = toScreen(wall.start)
  const p2 = toScreen(wall.end)
  const wallMinX = Math.min(p1.x, p2.x)
  const wallMaxX = Math.max(p1.x, p2.x)
  const wallMinY = Math.min(p1.y, p2.y)
  const wallMaxY = Math.max(p1.y, p2.y)

  return (
    wallMinX <= rect.maxX &&
    wallMaxX >= rect.minX &&
    wallMinY <= rect.maxY &&
    wallMaxY >= rect.minY
  )
}

function finishMarqueeSelection() {
  if (marqueeStart.value && marqueeCurrent.value) {
    const rect = {
      minX: Math.min(marqueeStart.value.x, marqueeCurrent.value.x),
      maxX: Math.max(marqueeStart.value.x, marqueeCurrent.value.x),
      minY: Math.min(marqueeStart.value.y, marqueeCurrent.value.y),
      maxY: Math.max(marqueeStart.value.y, marqueeCurrent.value.y),
    }

    // Ignore near-zero drags - those are plain clicks on empty canvas
    // (selection was already cleared, if appropriate, on pointerdown).
    if (rect.maxX - rect.minX > 4 || rect.maxY - rect.minY > 4) {
      const next = new Set(selectedWallIds.value)
      for (const wall of walls.value) {
        if (wallIntersectsRect(wall, rect)) next.add(wall.id)
      }
      selectedWallIds.value = next
    }
  }

  marqueeStart.value = null
  marqueeCurrent.value = null
  isMarqueeSelecting.value = false
}

// --- Unified pointer handlers (endpoint drag + marquee select + snap preview) ---
function onSvgPointerDown(event: PointerEvent) {
  if (isAddingWall.value) return

  const svgPoint = toSvgSpace(event)
  marqueeStart.value = svgPoint
  marqueeCurrent.value = svgPoint
  isMarqueeSelecting.value = true

  if (!(event.shiftKey || event.metaKey || event.ctrlKey)) {
    selectedWallIds.value = new Set()
  }
}

function onSvgPointerMove(event: PointerEvent) {
  if (dragging.value) {
    const svgPoint = toSvgSpace(event)
    const rawPoint = toPlanUnits(svgPoint.x, svgPoint.y)
    const planPoint = findSnapTarget(rawPoint, dragging.value.wallId) ?? rawPoint

    const wall = walls.value.find((w) => w.id === dragging.value!.wallId)
    if (wall) wall[dragging.value.end] = planPoint
    return
  }

  if (isAddingWall.value) {
    const svgPoint = toSvgSpace(event)
    const rawPoint = toPlanUnits(svgPoint.x, svgPoint.y)
    snapPreview.value = findSnapTarget(rawPoint)
    return
  }

  if (isMarqueeSelecting.value) {
    marqueeCurrent.value = toSvgSpace(event)
  }
}

function onSvgPointerUp() {
  if (dragging.value) {
    stopDrag()
    return
  }

  if (isMarqueeSelecting.value) {
    finishMarqueeSelection()
  }
}

// --- Adding a new wall: click two points on empty canvas ---
const isAddingWall = ref(false)
const pendingStart = ref<Point2D | null>(null)

function onCanvasClick(event: MouseEvent) {
  if (!isAddingWall.value) return

  const svgPoint = toSvgSpace(event)
  const rawPoint = toPlanUnits(svgPoint.x, svgPoint.y)
  const planPoint = findSnapTarget(rawPoint) ?? rawPoint

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
  snapPreview.value = null
}

function toggleAddWall() {
  isAddingWall.value = !isAddingWall.value
  pendingStart.value = null
  snapPreview.value = null
}

// --- Keyboard shortcuts: Delete/Backspace to remove selection, Escape to
// clear selection or cancel "add wall" mode ---
function onKeyDown(event: KeyboardEvent) {
  if ((event.key === 'Delete' || event.key === 'Backspace') && selectedWallIds.value.size > 0) {
    event.preventDefault()
    deleteSelected()
  } else if (event.key === 'Escape') {
    clearSelection()
    if (isAddingWall.value) toggleAddWall()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})

function confirmAndContinue() {
  emit('confirm', { ...props.floorPlan, walls: walls.value })
}
</script>

<template>
  <div class="editor">
    <button class="quick-3d-button" @click="confirmAndContinue">3D view →</button>

    <div class="toolbar">
      <p class="hint">
        Click a wall to select it. Shift/Ctrl/Cmd-click to select several, or
        drag on empty canvas for a selection box. Drag the white dots to
        reposition an endpoint - new or moved endpoints snap to nearby wall
        corners automatically. Delete/Backspace removes the selection,
        Escape clears it. Ctrl/Cmd + scroll, or the buttons below, to zoom.
      </p>
      <div class="actions">
        <button
          class="tool-button"
          :class="{ active: isAddingWall }"
          @click="toggleAddWall"
        >
          {{ isAddingWall ? 'Click two points…' : '+ Add wall' }}
        </button>
        <button class="tool-button" :disabled="walls.length === 0" @click="selectAll">
          Select all
        </button>
        <button
          class="tool-button danger"
          :disabled="selectedCount === 0"
          @click="deleteSelected"
        >
          Delete selected{{ selectedCount > 0 ? ` (${selectedCount})` : '' }}
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
      <p v-if="walls.length === 0 && !isAddingWall" class="empty-hint">
        Click "+ Add wall", then click two points on the canvas to draw your first wall.
      </p>

      <svg
        ref="svgRef"
        :width="canvasWidth * zoom"
        :height="canvasHeight * zoom"
        :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`"
        class="canvas"
        :class="{ 'add-mode': isAddingWall }"
        @pointerdown="onSvgPointerDown"
        @pointermove="onSvgPointerMove"
        @pointerup="onSvgPointerUp"
        @pointercancel="onSvgPointerUp"
        @click="onCanvasClick"
      >
        <line
          v-for="wall in walls"
          :key="wall.id"
          :x1="toScreen(wall.start).x"
          :y1="toScreen(wall.start).y"
          :x2="toScreen(wall.end).x"
          :y2="toScreen(wall.end).y"
          :class="['wall-line', { selected: isSelected(wall.id) }]"
          @click.stop="selectWall(wall.id, $event)"
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

        <circle
          v-if="isAddingWall && snapPreview"
          :cx="toScreen(snapPreview).x"
          :cy="toScreen(snapPreview).y"
          r="12"
          class="snap-indicator"
        />

        <rect
          v-if="isMarqueeSelecting && marqueeStart && marqueeCurrent"
          :x="Math.min(marqueeStart.x, marqueeCurrent.x)"
          :y="Math.min(marqueeStart.y, marqueeCurrent.y)"
          :width="Math.abs(marqueeCurrent.x - marqueeStart.x)"
          :height="Math.abs(marqueeCurrent.y - marqueeStart.y)"
          class="marquee"
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

.quick-3d-button {
  position: absolute;
  top: 16px;
  left: 160px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid #444;
  background: #1c1c1e;
  color: #e5e5e5;
  font-size: 13px;
  cursor: pointer;
}

.quick-3d-button:hover {
  border-color: #6b8afd;
}

.toolbar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: 620px;
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
  position: relative;
  max-width: 90vw;
  max-height: 60vh;
  overflow: auto;
  background: #16161a;
  border: 1px solid #2a2a2e;
  border-radius: 8px;
}

.empty-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  margin: 0;
  padding: 0 24px;
  max-width: 260px;
  text-align: center;
  font-size: 13px;
  color: #666;
  pointer-events: none;
  z-index: 1;
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

.snap-indicator {
  fill: none;
  stroke: #ffd166;
  stroke-width: 2;
  pointer-events: none;
}

.marquee {
  fill: rgba(107, 138, 253, 0.15);
  stroke: #6b8afd;
  stroke-width: 1;
  stroke-dasharray: 4 3;
  pointer-events: none;
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