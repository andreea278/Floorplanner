export interface Point2D {
  x: number
  y: number
}

export interface Wall {
  id: string
  start: Point2D
  end: Point2D
  height: number
  thickness: number
  /** Custom color override (hex, e.g. '#ff8844'). Falls back to the
   * default look when unset. */
  color?: string
}

export interface Door {
  id: string
  wallId: string
  offset: number
  width: number
  height: number
}

export interface Window {
  id: string
  wallId: string
  offset: number
  width: number
  height: number
  sillHeight: number
}

export type FurnitureKind =
  | 'sofa'
  | 'bed'
  | 'table'
  | 'chair'
  | 'toilet'
  | 'sink'
  | 'bathtub'
  | 'stove'
  | 'fridge'

export interface FurnitureItem {
  id: string
  kind: FurnitureKind
  x: number
  y: number
  rotation: number
  /** Custom color override (hex). Falls back to the kind's default material. */
  color?: string
}

export interface FloorPlan {
  id: string
  name: string
  unit: string
  walls: Wall[]
  doors: Door[]
  windows: Window[]
  furniture: FurnitureItem[]
}