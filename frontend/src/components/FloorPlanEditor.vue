<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { FloorPlan, Wall, Door, Window, Point2D } from '@/types/floorPlan'

const props = defineProps<{ floorPlan: FloorPlan }>()

const emit = defineEmits<{
  confirm: [floorPlan: FloorPlan]
}>()

// Local editable copies - we never mutate the prop directly (Vue best
// practice: props flow one way, down). All edits happen here; the parent
// only finds out when we emit 'confirm' (bottom CTA or the quick 3D-view
// toggle below both do this).
//
// Note: props.floorPlan is wrapped in a Vue reactive Proxy, and
// structuredClone() throws DataCloneError on that - so we use a JSON
// round-trip instead, which is safe here since the data is plain
// numbers/strings with no functions or special types. `?? []` guards
// against an older/partial plan object that predates doors/windows.
const walls = ref<Wall[]>(JSON.parse(JSON.stringify(props.floorPlan.walls)))
const doors = ref<Door[]>(JSON.parse(JSON.stringify(props.floorPlan.doors ?? [])))
const windows = ref<Window[]>(JSON.parse(JSON.stringify(props.floorPlan.windows ?? [])))

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

function wallById(id: string): Wall | undefined {
  return walls.value.find((w) => w.id === id)
}

// --- Snapping (for drawing/dragging wall endpoints, and for calibration
// clicks - snapping to a real corner gives a more accurate measurement
// than a freehand click) ---
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

// Live preview of the snap target while adding a wall or calibrating, so
// the user can see which corner they're about to lock onto before clicking.
const snapPreview = ref<Point2D | null>(null)

// --- Calibration ---
// Detection has no way to know real-world scale from pixels alone - the
// backend just assumes 100px/meter, which is a guess, not a measurement.
// This lets the user pick two points whose real-world distance they
// actually know (e.g. a wall they measured, or a known door width),
// type that distance in, and we rescale every wall's coordinates by the
// correction factor. This only needs two points and one number - it
// doesn't require going back to the original image.
const isCalibrating = ref(false)
const calibrationStart = ref<Point2D | null>(null)
const calibrationEnd = ref<Point2D | null>(null)
const measuredDistance = computed(() => {
  if (!calibrationStart.value || !calibrationEnd.value) return 0
  return Math.hypot(
    calibrationEnd.value.x - calibrationStart.value.x,
    calibrationEnd.value.y - calibrationStart.value.y,
  )
})
const realDistanceInput = ref<number | null>(null)

function toggleCalibrate() {
  isCalibrating.value = !isCalibrating.value
  calibrationStart.value = null
  calibrationEnd.value = null
  realDistanceInput.value = null
  if (isCalibrating.value) {
    // Calibration and "add wall/door/window" are mutually exclusive - one
    // click stream can't mean two different things at once.
    addMode.value = null
    pendingStart.value = null
    snapPreview.value = null
  }
}

function onCalibrationClick(point: Point2D) {
  if (!calibrationStart.value) {
    calibrationStart.value = point
  } else if (!calibrationEnd.value) {
    calibrationEnd.value = point
  }
}

function applyCalibration() {
  if (!realDistanceInput.value || realDistanceInput.value <= 0 || measuredDistance.value === 0) {
    return
  }

  const factor = realDistanceInput.value / measuredDistance.value

  // Scale every wall coordinate uniformly - height/thickness are left
  // alone (they're reasonable fixed defaults, not something calibration
  // is meant to correct).
  walls.value = walls.value.map((wall) => ({
    ...wall,
    start: { x: wall.start.x * factor, y: wall.start.y * factor },
    end: { x: wall.end.x * factor, y: wall.end.y * factor },
  }))

  // Door/window offsets are a distance along their wall, in the same units
  // as the wall coordinates just rescaled above - without this they'd
  // stay at their old, pre-calibration offset and visually drift off their
  // wall once its length changes. Width/height/sillHeight are real
  // physical measurements the user set directly (or left at sensible
  // defaults), not something derived from the uncalibrated coordinates,
  // so those are left untouched.
  doors.value = doors.value.map((door) => ({ ...door, offset: door.offset * factor }))
  windows.value = windows.value.map((win) => ({ ...win, offset: win.offset * factor }))

  toggleCalibrate()
}

function cancelCalibration() {
  toggleCalibrate()
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
// A Set of ids so several walls/doors/windows can be selected at once
// (shift/ctrl/cmd-click to toggle one in or out, or drag a marquee box
// over several). Ids are unique across all three kinds.
const selectedIds = ref<Set<string>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)

function isSelected(id: string): boolean {
  return selectedIds.value.has(id)
}

function selectItem(id: string, event: MouseEvent) {
  const additive = event.shiftKey || event.metaKey || event.ctrlKey
  const next = new Set(selectedIds.value)

  if (additive) {
    if (next.has(id)) next.delete(id)
    else next.add(id)
  } else {
    next.clear()
    next.add(id)
  }

  selectedIds.value = next
}

function selectAll() {
  selectedIds.value = new Set([
    ...walls.value.map((w) => w.id),
    ...doors.value.map((d) => d.id),
    ...windows.value.map((w) => w.id),
  ])
}

function clearSelection() {
  selectedIds.value = new Set()
}

function deleteSelected() {
  if (selectedIds.value.size === 0) return

  const remainingWalls = walls.value.filter((w) => !selectedIds.value.has(w.id))
  const remainingWallIds = new Set(remainingWalls.map((w) => w.id))

  walls.value = remainingWalls
  // A door/window also disappears if it was selected directly, OR if its
  // wall just got deleted (no orphaned openings pointing at a missing wall).
  doors.value = doors.value.filter(
    (d) => !selectedIds.value.has(d.id) && remainingWallIds.has(d.wallId),
  )
  windows.value = windows.value.filter(
    (w) => !selectedIds.value.has(w.id) && remainingWallIds.has(w.wallId),
  )

  clearSelection()
}

// --- Dragging a wall endpoint ---
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

// If a wall gets shorter than the doors/windows placed on it, pull their
// offsets back in so they can't end up hanging past the new wall end.
function clampOpeningsForWall(wallId: string) {
  const wall = wallById(wallId)
  if (!wall) return
  const length = Math.hypot(wall.end.x - wall.start.x, wall.end.y - wall.start.y)

  for (const item of [...doors.value, ...windows.value]) {
    if (item.wallId !== wallId) continue
    const halfWidth = Math.min(item.width / 2, Math.max(length / 2 - 0.01, 0))
    item.offset = Math.min(Math.max(item.offset, halfWidth), Math.max(halfWidth, length - halfWidth))
  }
}

// --- Dragging a door/window along its wall ---
const draggingOpening = ref<{ id: string; kind: 'door' | 'window' } | null>(null)

function startDragOpening(event: PointerEvent, id: string, kind: 'door' | 'window') {
  draggingOpening.value = { id, kind }
  ;(event.target as Element).setPointerCapture(event.pointerId)
}

// --- Marquee (rubber-band) selection ---
// Dragging on empty canvas draws a selection box; any wall/door/window
// whose span overlaps it gets added to the selection on release.
const marqueeStart = ref<{ x: number; y: number } | null>(null)
const marqueeCurrent = ref<{ x: number; y: number } | null>(null)
const isMarqueeSelecting = ref(false)

function segmentIntersectsRect(
  p1: { x: number; y: number },
  p2: { x: number; y: number },
  rect: { minX: number; maxX: number; minY: number; maxY: number },
): boolean {
  const minX = Math.min(p1.x, p2.x)
  const maxX = Math.max(p1.x, p2.x)
  const minY = Math.min(p1.y, p2.y)
  const maxY = Math.max(p1.y, p2.y)
  return minX <= rect.maxX && maxX >= rect.minX && minY <= rect.maxY && maxY >= rect.minY
}

function openingSpan(opening: { wallId: string; offset: number; width: number }) {
  const wall = wallById(opening.wallId)
  if (!wall) return null

  const dx = wall.end.x - wall.start.x
  const dy = wall.end.y - wall.start.y
  const length = Math.hypot(dx, dy)
  if (length < 1e-9) return null

  const ux = dx / length
  const uy = dy / length
  const halfWidth = opening.width / 2
  const t1 = opening.offset - halfWidth
  const t2 = opening.offset + halfWidth

  return {
    p1: { x: wall.start.x + ux * t1, y: wall.start.y + uy * t1 },
    p2: { x: wall.start.x + ux * t2, y: wall.start.y + uy * t2 },
    mid: { x: wall.start.x + ux * opening.offset, y: wall.start.y + uy * opening.offset },
  }
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
      const next = new Set(selectedIds.value)

      for (const wall of walls.value) {
        if (segmentIntersectsRect(toScreen(wall.start), toScreen(wall.end), rect)) {
          next.add(wall.id)
        }
      }
      for (const door of doors.value) {
        const span = openingSpan(door)
        if (span && segmentIntersectsRect(toScreen(span.p1), toScreen(span.p2), rect)) {
          next.add(door.id)
        }
      }
      for (const win of windows.value) {
        const span = openingSpan(win)
        if (span && segmentIntersectsRect(toScreen(span.p1), toScreen(span.p2), rect)) {
          next.add(win.id)
        }
      }

      selectedIds.value = next
    }
  }

  marqueeStart.value = null
  marqueeCurrent.value = null
  isMarqueeSelecting.value = false
}

// --- Unified pointer handlers (endpoint drag, opening drag, marquee, snap) ---
function onSvgPointerDown(event: PointerEvent) {
  if (addMode.value !== null || isCalibrating.value) return

  const svgPoint = toSvgSpace(event)
  marqueeStart.value = svgPoint
  marqueeCurrent.value = svgPoint
  isMarqueeSelecting.value = true

  if (!(event.shiftKey || event.metaKey || event.ctrlKey)) {
    selectedIds.value = new Set()
  }
}

function onSvgPointerMove(event: PointerEvent) {
  if (dragging.value) {
    const svgPoint = toSvgSpace(event)
    const rawPoint = toPlanUnits(svgPoint.x, svgPoint.y)
    const planPoint = findSnapTarget(rawPoint, dragging.value.wallId) ?? rawPoint

    const wall = walls.value.find((w) => w.id === dragging.value!.wallId)
    if (wall) {
      wall[dragging.value.end] = planPoint
      clampOpeningsForWall(wall.id)
    }
    return
  }

  if (draggingOpening.value) {
    const svgPoint = toSvgSpace(event)
    const point = toPlanUnits(svgPoint.x, svgPoint.y)
    const list = draggingOpening.value.kind === 'door' ? doors.value : windows.value
    const item = list.find((o) => o.id === draggingOpening.value!.id)
    const wall = item && wallById(item.wallId)

    if (item && wall) {
      const dx = wall.end.x - wall.start.x
      const dy = wall.end.y - wall.start.y
      const lengthSq = dx * dx + dy * dy
      if (lengthSq > 1e-9) {
        const length = Math.sqrt(lengthSq)
        let t = ((point.x - wall.start.x) * dx + (point.y - wall.start.y) * dy) / lengthSq
        t = Math.min(1, Math.max(0, t))
        const halfWidth = Math.min(item.width / 2, Math.max(length / 2 - 0.01, 0))
        item.offset = Math.min(Math.max(t * length, halfWidth), Math.max(halfWidth, length - halfWidth))
      }
    }
    return
  }

  if (addMode.value === 'wall' || isCalibrating.value) {
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
  if (draggingOpening.value) {
    draggingOpening.value = null
    return
  }
  if (isMarqueeSelecting.value) {
    finishMarqueeSelection()
  }
}

// --- Add mode: 'wall' | 'door' | 'window' | null ---
const addMode = ref<'wall' | 'door' | 'window' | null>(null)
const isAddingWall = computed(() => addMode.value === 'wall')
const pendingStart = ref<Point2D | null>(null)

function toggleMode(mode: 'wall' | 'door' | 'window') {
  addMode.value = addMode.value === mode ? null : mode
  pendingStart.value = null
  snapPreview.value = null
  if (addMode.value !== null) {
    // Adding geometry and calibrating are mutually exclusive.
    isCalibrating.value = false
    calibrationStart.value = null
    calibrationEnd.value = null
  }
}

const WALL_HIT_DISTANCE = 0.4 // meters - how close a click needs to land to "count" as being on a wall

function findWallProjection(
  point: Point2D,
): { wallId: string; offset: number; wallLength: number } | null {
  let best: { wallId: string; offset: number; wallLength: number; distance: number } | null = null

  for (const wall of walls.value) {
    const dx = wall.end.x - wall.start.x
    const dy = wall.end.y - wall.start.y
    const lengthSq = dx * dx + dy * dy
    if (lengthSq < 1e-9) continue
    const length = Math.sqrt(lengthSq)

    let t = ((point.x - wall.start.x) * dx + (point.y - wall.start.y) * dy) / lengthSq
    t = Math.min(1, Math.max(0, t))

    const projX = wall.start.x + t * dx
    const projY = wall.start.y + t * dy
    const distance = Math.hypot(point.x - projX, point.y - projY)

    if (distance < WALL_HIT_DISTANCE && (!best || distance < best.distance)) {
      best = { wallId: wall.id, offset: t * length, wallLength: length, distance }
    }
  }

  return best ? { wallId: best.wallId, offset: best.offset, wallLength: best.wallLength } : null
}

function addOpening(kind: 'door' | 'window', wallId: string, rawOffset: number, length: number) {
  const defaultWidth = kind === 'door' ? 0.9 : 1.2
  const halfWidth = Math.min(defaultWidth / 2, Math.max(length / 2 - 0.01, 0))
  const offset = Math.min(Math.max(rawOffset, halfWidth), Math.max(halfWidth, length - halfWidth))

  if (kind === 'door') {
    doors.value.push({
      id: `door-${crypto.randomUUID().slice(0, 8)}`,
      wallId,
      offset,
      width: defaultWidth,
      height: 2.1,
    })
  } else {
    windows.value.push({
      id: `window-${crypto.randomUUID().slice(0, 8)}`,
      wallId,
      offset,
      width: defaultWidth,
      height: 1.2,
      sillHeight: 0.9,
    })
  }

  addMode.value = null
}

// Clicking directly on a wall handles three cases: calibrating (register
// the calibration point), placing a door/window (most precise path since
// we already know exactly which wall was hit), or plain selection.
function onWallClick(wall: Wall, event: MouseEvent) {
  if (isCalibrating.value) {
    const svgPoint = toSvgSpace(event)
    const rawPoint = toPlanUnits(svgPoint.x, svgPoint.y)
    const planPoint = findSnapTarget(rawPoint) ?? rawPoint
    onCalibrationClick(planPoint)
    return
  }

  if (addMode.value === 'door' || addMode.value === 'window') {
    const svgPoint = toSvgSpace(event)
    const clickPoint = toPlanUnits(svgPoint.x, svgPoint.y)

    const dx = wall.end.x - wall.start.x
    const dy = wall.end.y - wall.start.y
    const lengthSq = dx * dx + dy * dy
    if (lengthSq < 1e-9) return
    const length = Math.sqrt(lengthSq)

    let t = ((clickPoint.x - wall.start.x) * dx + (clickPoint.y - wall.start.y) * dy) / lengthSq
    t = Math.min(1, Math.max(0, t))

    addOpening(addMode.value, wall.id, t * length, length)
  } else {
    selectItem(wall.id, event)
  }
}

// Clicking near (but not exactly on) a wall's thin line, or on empty canvas.
function onCanvasClick(event: MouseEvent) {
  if (addMode.value === null && !isCalibrating.value) return

  const svgPoint = toSvgSpace(event)
  const rawPoint = toPlanUnits(svgPoint.x, svgPoint.y)

  if (isCalibrating.value) {
    const planPoint = findSnapTarget(rawPoint) ?? rawPoint
    onCalibrationClick(planPoint)
    return
  }

  if (addMode.value === 'wall') {
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
    addMode.value = null
    snapPreview.value = null
  } else if (addMode.value === 'door' || addMode.value === 'window') {
    const hit = findWallProjection(rawPoint)
    if (!hit) return // not close enough to any wall - ignore
    addOpening(addMode.value, hit.wallId, hit.offset, hit.wallLength)
  }
}

// --- Keyboard shortcuts ---
function onKeyDown(event: KeyboardEvent) {
  if ((event.key === 'Delete' || event.key === 'Backspace') && selectedIds.value.size > 0) {
    event.preventDefault()
    deleteSelected()
  } else if (event.key === 'Escape') {
    clearSelection()
    addMode.value = null
    pendingStart.value = null
    snapPreview.value = null
    if (isCalibrating.value) toggleCalibrate()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})

function confirmAndContinue() {
  emit('confirm', {
    ...props.floorPlan,
    walls: walls.value,
    doors: doors.value,
    windows: windows.value,
  })
}
</script>

<template>
  <div class="editor">
    <button class="quick-3d-button" @click="confirmAndContinue">3D view →</button>

    <div class="toolbar">
      <p class="hint">
        Click a wall/door/window to select it. Shift/Ctrl/Cmd-click to select
        several, or drag on empty canvas for a selection box. Drag the dots to
        reposition - new or moved wall endpoints snap to nearby corners.
        Delete/Backspace removes the selection, Escape clears it/cancels the
        current tool. Ctrl/Cmd + scroll, or the buttons below, to zoom.
      </p>

      <div class="legend">
        <span class="legend-item"><span class="swatch wall" /> Wall</span>
        <span class="legend-item"><span class="swatch door" /> Door</span>
        <span class="legend-item"><span class="swatch window" /> Window</span>
      </div>

      <div class="actions">
        <button class="tool-button" :class="{ active: addMode === 'wall' }" @click="toggleMode('wall')">
          {{ addMode === 'wall' ? 'Click two points…' : '+ Add wall' }}
        </button>
        <button
          class="tool-button"
          :class="{ active: addMode === 'door' }"
          :disabled="walls.length === 0"
          @click="toggleMode('door')"
        >
          {{ addMode === 'door' ? 'Click a wall…' : '+ Add door' }}
        </button>
        <button
          class="tool-button"
          :class="{ active: addMode === 'window' }"
          :disabled="walls.length === 0"
          @click="toggleMode('window')"
        >
          {{ addMode === 'window' ? 'Click a wall…' : '+ Add window' }}
        </button>
        <button
          class="tool-button"
          :class="{ active: isCalibrating }"
          :disabled="walls.length === 0"
          @click="toggleCalibrate"
        >
          📏 Calibrate
        </button>
        <button class="tool-button" :disabled="walls.length === 0" @click="selectAll">
          Select all
        </button>
        <button class="tool-button danger" :disabled="selectedCount === 0" @click="deleteSelected">
          Delete selected{{ selectedCount > 0 ? ` (${selectedCount})` : '' }}
        </button>
        <span class="divider" />
        <button class="tool-button" @click="zoomOut">−</button>
        <button class="tool-button zoom-label" @click="zoomReset">{{ Math.round(zoom * 100) }}%</button>
        <button class="tool-button" @click="zoomIn">+</button>
      </div>

      <div v-if="isCalibrating" class="calibration-panel">
        <p v-if="!calibrationStart" class="calibration-step">
          Click one end of something whose real length you know (a wall, a door).
        </p>
        <p v-else-if="!calibrationEnd" class="calibration-step">Now click the other end.</p>
        <div v-else class="calibration-input">
          <span>That's {{ measuredDistance.toFixed(2) }} plan units. Its real length is</span>
          <input
            v-model.number="realDistanceInput"
            type="number"
            step="0.01"
            min="0"
            placeholder="meters"
            class="calibration-number"
          />
          <span>meters.</span>
          <button
            class="tool-button primary"
            :disabled="!realDistanceInput || realDistanceInput <= 0"
            @click="applyCalibration"
          >
            Apply
          </button>
          <button class="tool-button" @click="cancelCalibration">Cancel</button>
        </div>
      </div>
    </div>

    <div class="canvas-wrapper" @wheel="onWheel">
      <p v-if="walls.length === 0 && addMode === null" class="empty-hint">
        Click "+ Add wall" to draw your first wall. Once you have walls, use
        "+ Add door" or "+ Add window" and click on a wall to place one.
      </p>

      <svg
        ref="svgRef"
        :width="canvasWidth * zoom"
        :height="canvasHeight * zoom"
        :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`"
        class="canvas"
        :class="{ 'add-mode': addMode !== null || isCalibrating }"
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
          @click.stop="onWallClick(wall, $event)"
        />

        <template v-for="door in doors" :key="door.id">
          <template v-if="openingSpan(door)">
            <line
              :x1="toScreen(openingSpan(door)!.p1).x"
              :y1="toScreen(openingSpan(door)!.p1).y"
              :x2="toScreen(openingSpan(door)!.p2).x"
              :y2="toScreen(openingSpan(door)!.p2).y"
              :class="['door-span', { selected: isSelected(door.id) }]"
              @click.stop="selectItem(door.id, $event)"
            />
            <circle
              :cx="toScreen(openingSpan(door)!.mid).x"
              :cy="toScreen(openingSpan(door)!.mid).y"
              r="6"
              class="opening-handle door-handle"
              @click.stop="selectItem(door.id, $event)"
              @pointerdown.stop="(e) => startDragOpening(e, door.id, 'door')"
            />
          </template>
        </template>

        <template v-for="win in windows" :key="win.id">
          <template v-if="openingSpan(win)">
            <line
              :x1="toScreen(openingSpan(win)!.p1).x"
              :y1="toScreen(openingSpan(win)!.p1).y"
              :x2="toScreen(openingSpan(win)!.p2).x"
              :y2="toScreen(openingSpan(win)!.p2).y"
              :class="['window-span', { selected: isSelected(win.id) }]"
              @click.stop="selectItem(win.id, $event)"
            />
            <circle
              :cx="toScreen(openingSpan(win)!.mid).x"
              :cy="toScreen(openingSpan(win)!.mid).y"
              r="6"
              class="opening-handle window-handle"
              @click.stop="selectItem(win.id, $event)"
              @pointerdown.stop="(e) => startDragOpening(e, win.id, 'window')"
            />
          </template>
        </template>

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

        <circle v-if="pendingStart" :cx="toScreen(pendingStart).x" :cy="toScreen(pendingStart).y" r="6" class="pending-point" />

        <circle
          v-if="(addMode === 'wall' || isCalibrating) && snapPreview"
          :cx="toScreen(snapPreview).x"
          :cy="toScreen(snapPreview).y"
          r="12"
          class="snap-indicator"
        />

        <template v-if="isCalibrating">
          <line
            v-if="calibrationStart && calibrationEnd"
            :x1="toScreen(calibrationStart).x"
            :y1="toScreen(calibrationStart).y"
            :x2="toScreen(calibrationEnd).x"
            :y2="toScreen(calibrationEnd).y"
            class="calibration-line"
          />
          <circle
            v-if="calibrationStart"
            :cx="toScreen(calibrationStart).x"
            :cy="toScreen(calibrationStart).y"
            r="7"
            class="calibration-point"
          />
          <circle
            v-if="calibrationEnd"
            :cx="toScreen(calibrationEnd).x"
            :cy="toScreen(calibrationEnd).y"
            r="7"
            class="calibration-point"
          />
        </template>

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

    <button class="continue-button" @click="confirmAndContinue">Generate 3D Model →</button>
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
  max-width: 680px;
  text-align: center;
}

.hint {
  font-size: 13px;
  color: #999;
  margin: 0;
}

.legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #aaa;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.swatch {
  width: 14px;
  height: 4px;
  border-radius: 2px;
  display: inline-block;
}

.swatch.wall {
  background: #6b8afd;
}

.swatch.door {
  background: #d9a066;
}

.swatch.window {
  background: #7fd0e8;
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

.tool-button.primary {
  border-color: #6b8afd;
  background: #6b8afd;
  color: #0d0d0f;
  font-weight: 600;
}

.tool-button.primary:hover:not(:disabled) {
  background: #82a0ff;
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
  max-width: 280px;
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

.door-span {
  stroke: #d9a066;
  stroke-width: 6;
  cursor: pointer;
}

.window-span {
  stroke: #7fd0e8;
  stroke-width: 6;
  cursor: pointer;
}

.wall-line.selected,
.door-span.selected,
.window-span.selected {
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

.opening-handle {
  cursor: grab;
  touch-action: none;
  stroke: #16161a;
  stroke-width: 1.5;
}

.door-handle {
  fill: #d9a066;
}

.window-handle {
  fill: #7fd0e8;
}

.calibration-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #1c1c1e;
  border: 1px solid #ffd166;
  font-size: 13px;
  flex-wrap: wrap;
}

.calibration-step {
  margin: 0;
  color: #ffd166;
}

.calibration-input {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: #ccc;
}

.calibration-number {
  width: 80px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid #444;
  background: #101012;
  color: #e5e5e5;
  font-size: 13px;
}

.calibration-point {
  fill: #ffd166;
  stroke: #0d0d0f;
  stroke-width: 2;
}

.calibration-line {
  stroke: #ffd166;
  stroke-width: 2;
  stroke-dasharray: 5 4;
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