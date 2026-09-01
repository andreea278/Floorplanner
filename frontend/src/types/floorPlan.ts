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
}

export interface Door {
  id: string
  wallId: string
  /** Distance in meters from the wall's start point to the door's center. */
  offset: number
  width: number
  height: number
}

export interface Window {
  id: string
  wallId: string
  /** Distance in meters from the wall's start point to the window's center. */
  offset: number
  width: number
  height: number
  /** Height of the window sill above the floor, in meters. */
  sillHeight: number
}

export interface FloorPlan {
  id: string
  name: string
  unit: string
  walls: Wall[]
  doors: Door[]
  windows: Window[]
}