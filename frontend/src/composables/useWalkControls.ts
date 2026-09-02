import { ref } from 'vue'
import * as THREE from 'three'

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
 * WASD (+ Space/Shift) movement that translates the camera along its own
 * current facing direction - orientation itself is owned entirely by
 * useFirstPersonLook (or, in orbit mode, by OrbitControls); this
 * composable only ever moves camera.position, never rotates anything.
 */
export function useWalkControls(
  camera: THREE.PerspectiveCamera,
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
    event.preventDefault()
    move[action] = true
    syncIsMoving()
  }

  function onKeyUp(event: KeyboardEvent) {
    const action = KEY_BINDINGS[event.code]
    if (!action) return
    move[action] = false
    syncIsMoving()
  }

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

  function update(delta: number) {
    if (!isMoving.value) return

    camera.updateMatrixWorld()
    right.setFromMatrixColumn(camera.matrixWorld, 0)
    back.setFromMatrixColumn(camera.matrixWorld, 2)

    // Flatten to the horizontal plane so WASD feels like walking even
    // while looking up/down - altitude is handled explicitly via
    // Space/Shift.
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
    }

    if (move.up || move.down) {
      camera.position.y += moveSpeed * delta * ((move.up ? 1 : 0) - (move.down ? 1 : 0))
    }
  }

  function dispose() {
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
    window.removeEventListener('blur', onBlur)
  }

  return { update, dispose, isMoving }
}