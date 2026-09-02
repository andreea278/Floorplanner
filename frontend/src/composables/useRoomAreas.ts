import type { Point2D, Wall } from '@/types/floorPlan'

export interface RoomArea {
  areaM2: number
  centroid: Point2D
  polygon: Point2D[]
}

const SNAP_EPS = 0.05 // meters

function dist(a: Point2D, b: Point2D): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

function snapKey(p: Point2D): string {
  return `${Math.round(p.x / SNAP_EPS)}:${Math.round(p.y / SNAP_EPS)}`
}

/**
 * Cuts every wall at any point where another wall's endpoint touches its
 * interior (a T-junction - extremely common in real floor plans, where an
 * interior partition ends partway along a longer wall rather than exactly
 * at one of its corners). Planar-graph face-finding below needs a proper
 * shared node at every such junction, or faces won't close correctly.
 */
function splitWallsAtTJunctions(segments: Array<[Point2D, Point2D]>): Array<[Point2D, Point2D]> {
  const allPoints: Point2D[] = []
  for (const [s, e] of segments) {
    allPoints.push(s, e)
  }

  const result: Array<[Point2D, Point2D]> = []

  for (const [s, e] of segments) {
    const length = dist(s, e)
    if (length < 1e-9) continue
    const ux = (e.x - s.x) / length
    const uy = (e.y - s.y) / length

    const cutTs = new Set<number>([0, length])
    for (const p of allPoints) {
      const t = (p.x - s.x) * ux + (p.y - s.y) * uy
      if (t > SNAP_EPS && t < length - SNAP_EPS) {
        const projX = s.x + ux * t
        const projY = s.y + uy * t
        if (Math.hypot(p.x - projX, p.y - projY) < SNAP_EPS) {
          cutTs.add(t)
        }
      }
    }

    const ts = Array.from(cutTs).sort((a, b) => a - b)
    for (let i = 0; i < ts.length - 1; i++) {
      const t1 = ts[i]!
      const t2 = ts[i + 1]!
      if (t2 - t1 < SNAP_EPS) continue
      result.push([
        { x: s.x + ux * t1, y: s.y + uy * t1 },
        { x: s.x + ux * t2, y: s.y + uy * t2 },
      ])
    }
  }

  return result
}

/**
 * Detects closed rooms formed by a set of walls and returns each one's
 * area, centroid, and polygon - using the walls' full extent regardless
 * of any doors/windows on them (an opening in a wall doesn't disconnect
 * the room it bounds).
 *
 * This is a planar straight-line graph face-finding algorithm: build a
 * graph from wall endpoints (snapped together within SNAP_EPS), split at
 * T-junctions, then trace each face by always taking the next edge in
 * angular order around each node. The single unbounded "outer" face
 * (everything outside the building) is discarded by dropping the face
 * with the largest absolute area - inner rooms are always much smaller
 * than the sum of the whole exterior boundary.
 *
 * This is a best-effort geometric heuristic, not a guarantee: severely
 * malformed plans (walls that don't actually meet, self-intersecting
 * layouts) can produce zero, extra, or wrong-shaped faces. Treat the
 * result as a helpful estimate, not authoritative floor area.
 *
 * Note on the non-null assertions below (`nodes[i]!` etc.): every index
 * used here is produced by this function's own bookkeeping (getNode,
 * loop bounds tied to array.length) and is always in range - they're
 * needed only because `noUncheckedIndexedAccess` can't see that.
 */
export function findRoomAreas(walls: Wall[]): RoomArea[] {
  if (walls.length < 3) return []

  const segments: Array<[Point2D, Point2D]> = walls.map((w) => [w.start, w.end])
  const split = splitWallsAtTJunctions(segments)

  const nodeIndex = new Map<string, number>()
  const nodes: Point2D[] = []
  function getNode(p: Point2D): number {
    const key = snapKey(p)
    let idx = nodeIndex.get(key)
    if (idx === undefined) {
      idx = nodes.length
      nodeIndex.set(key, idx)
      nodes.push(p)
    }
    return idx
  }

  const edgeSet = new Set<string>()
  const edges: Array<[number, number]> = []
  for (const [s, e] of split) {
    const a = getNode(s)
    const b = getNode(e)
    if (a === b) continue
    for (const [u, v] of [
      [a, b],
      [b, a],
    ] as [number, number][]) {
      const key = `${u}:${v}`
      if (!edgeSet.has(key)) {
        edgeSet.add(key)
        edges.push([u, v])
      }
    }
  }

  const adjacency = new Map<number, Array<{ angle: number; to: number }>>()
  for (const [a, b] of edges) {
    const angle = Math.atan2(nodes[b]!.y - nodes[a]!.y, nodes[b]!.x - nodes[a]!.x)
    if (!adjacency.has(a)) adjacency.set(a, [])
    adjacency.get(a)!.push({ angle, to: b })
  }
  for (const list of adjacency.values()) {
    list.sort((a, b) => a.angle - b.angle)
  }

  function nextHalfEdge(u: number, v: number): number {
    const incomingAngle = Math.atan2(nodes[u]!.y - nodes[v]!.y, nodes[u]!.x - nodes[v]!.x)
    const candidates = adjacency.get(v) ?? []
    let best: { delta: number; to: number } | null = null
    for (const { angle, to } of candidates) {
      if (to === u && Math.abs(angle - incomingAngle) < 1e-9) continue
      let delta = (angle - incomingAngle) % (2 * Math.PI)
      if (delta <= 1e-9) delta += 2 * Math.PI
      if (!best || delta < best.delta) best = { delta, to }
    }
    return best ? best.to : u
  }

  const visited = new Set<string>()
  const faces: Array<{ signedArea: number; polygon: Point2D[] }> = []

  for (const [a, b] of edges) {
    const startKey = `${a}:${b}`
    if (visited.has(startKey)) continue

    const face = [a, b]
    visited.add(startKey)
    let u = a
    let v = b
    let closed = false

    for (let i = 0; i < 10000; i++) {
      const w = nextHalfEdge(u, v)
      const key = `${v}:${w}`
      if (visited.has(key)) break
      visited.add(key)
      face.push(w)
      u = v
      v = w
      if (u === a && v === b) {
        face.pop()
        closed = true
        break
      }
    }
    if (!closed) continue

    const polygon = face.map((i) => nodes[i]!)
    let area2 = 0
    for (let i = 0; i < polygon.length; i++) {
      const p1 = polygon[i]!
      const p2 = polygon[(i + 1) % polygon.length]!
      area2 += p1.x * p2.y - p2.x * p1.y
    }
    faces.push({ signedArea: area2 / 2, polygon })
  }

  if (faces.length === 0) return []

  faces.sort((a, b) => Math.abs(b.signedArea) - Math.abs(a.signedArea))
  const inner = faces.slice(1) // drop the outer/unbounded face

  return inner.map(({ signedArea, polygon }) => {
    const area = Math.abs(signedArea)
    const cx = polygon.reduce((sum, p) => sum + p.x, 0) / polygon.length
    const cy = polygon.reduce((sum, p) => sum + p.y, 0) / polygon.length
    return { areaM2: area, centroid: { x: cx, y: cy }, polygon }
  })
}