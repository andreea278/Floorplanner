import { ref } from 'vue'
import * as THREE from 'three'
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

export interface UseWalkControlsOptions {
  /** Ground movement speed, in scene units (meters) per second. */
  moveSpeed?: number
}

interface MoveState {
  forward: boolean
  backward: boolean
  left: boolean
  right: boolean
  up: boolean
  down: boolean
}

const KEY_BINDINGS: Record<string, keyof MoveState> = {
  KeyW: 'forward',
  ArrowUp: 'forward',
  KeyS: 'backward',
  ArrowDown: 'backward',
  KeyA: 'left',
  ArrowLeft: 'left',
  KeyD: 'right',
  ArrowRight: 'right',
  Space: 'up',
  ShiftLeft: 'down',
  ShiftRight: 'down',
}

/**
 * WASD (+ Space/Shift) free movement layered on top of an existing
 * OrbitControls instance. Mouse-drag rotate and wheel zoom stay owned by
 * OrbitControls untouched - this only translates the camera and its orbit
 * target together, so orbiting always pivots around wherever you currently
 * are instead of the original fixed point.
 */
export function useWalkControls(
  camera: THREE.PerspectiveCamera,
  orbitControls: OrbitControls,
  options: UseWalkControlsOptions = {},
) {
  const moveSpeed = options.moveSpeed ?? 4

  const move: MoveState = {
    forward: false,
    backward: false,
    left: false,
    right: false,
    up: false,
    down: false,
  }

  const isMoving = ref(false)

  function syncIsMoving() {
    isMoving.value =
      move.forward || move.backward || move.left || move.right || move.up || move.down
  }

  function onKeyDown(event: KeyboardEvent) {
    const action = KEY_BINDINGS[event.code]
    if (!action) return
    event.preventDefault() // stop Space from scrolling the page, etc.
    move[action] = true
    syncIsMoving()
  }

  function onKeyUp(event: KeyboardEvent) {
    const action = KEY_BINDINGS[event.code]
    if (!action) return
    move[action] = false
    syncIsMoving()
  }

  // If the window loses focus mid-keypress (alt-tab, devtools, etc.) there's
  // no matching keyup - without this the camera could drift forever.
  function onBlur() {
    ;(Object.keys(move) as (keyof MoveState)[]).forEach((key) => {
      move[key] = false
    })
    isMoving.value = false
  }

  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('blur', onBlur)

  const right = new THREE.Vector3()
  const back = new THREE.Vector3()
  const offset = new THREE.Vector3()
  const vertical = new THREE.Vector3()

  function update(delta: number) {
    if (!isMoving.value) return

    camera.updateMatrixWorld()
    right.setFromMatrixColumn(camera.matrixWorld, 0)
    back.setFromMatrixColumn(camera.matrixWorld, 2)

    // Flatten to the horizontal plane so WASD feels like walking even while
    // looking up/down - altitude is handled explicitly via Space/Shift.
    right.y = 0
    back.y = 0
    right.normalize()
    back.normalize()

    offset.set(0, 0, 0)
    if (move.forward) offset.sub(back)
    if (move.backward) offset.add(back)
    if (move.right) offset.add(right)
    if (move.left) offset.sub(right)

    if (offset.lengthSq() > 0) {
      offset.normalize().multiplyScalar(moveSpeed * delta)
      camera.position.add(offset)
      orbitControls.target.add(offset)
    }

    if (move.up || move.down) {
      const step = moveSpeed * delta * ((move.up ? 1 : 0) - (move.down ? 1 : 0))
      vertical.set(0, step, 0)
      camera.position.add(vertical)
      orbitControls.target.add(vertical)
    }
  }

  function dispose() {
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
    window.removeEventListener('blur', onBlur)
  }

  return { update, dispose, isMoving }
}