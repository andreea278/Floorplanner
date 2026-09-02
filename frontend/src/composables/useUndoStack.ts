import { shallowRef } from 'vue'

/**
 * A simple snapshot-based undo stack. Callers push a deep-cloned snapshot
 * of their editable state right BEFORE a mutating action (once per
 * user-visible action - e.g. once at the start of a drag, not once per
 * pointermove frame), so undo() reverts one whole action at a time
 * instead of one tiny intermediate step.
 *
 * Uses shallowRef, not ref: with a generic T, plain ref<T[]>([]) applies
 * Vue's UnwrapRef<T> to the element type, which can stop matching T
 * exactly and breaks push/pop's typing. shallowRef sidesteps that
 * entirely - and it's also the right semantic choice here, since these
 * snapshots are swapped in/out wholesale, never mutated in place, so they
 * don't need Vue's deep reactivity anyway.
 */
export function useUndoStack<T>(maxSize = 50) {
  const stack = shallowRef<T[]>([])

  function push(snapshot: T) {
    stack.value = [...stack.value, snapshot]
    if (stack.value.length > maxSize) {
      stack.value = stack.value.slice(1)
    }
  }

  function undo(): T | undefined {
    if (stack.value.length === 0) return undefined
    const next = stack.value[stack.value.length - 1]
    stack.value = stack.value.slice(0, -1)
    return next
  }

  function canUndo(): boolean {
    return stack.value.length > 0
  }

  function clear() {
    stack.value = []
  }

  return { push, undo, canUndo, clear }
}