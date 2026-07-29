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

export interface FloorPlan {
  id: string
  name: string
  unit: string
  walls: Wall[]
}