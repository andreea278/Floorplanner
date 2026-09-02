import type { FloorPlan } from '@/types/floorPlan'

export const mockFloorPlan: FloorPlan = {
  id: 'mock-floorplan',
  name: 'Mock Floor Plan',
  unit: 'meters',
  walls: [
    { id: 'wall-1', start: { x: 0, y: 0 }, end: { x: 10, y: 0 }, height: 2.7, thickness: 0.2 },
    { id: 'wall-2', start: { x: 6, y: 0 }, end: { x: 6, y: 4 }, height: 2.7, thickness: 0.2 },
    { id: 'wall-3', start: { x: 6, y: 4 }, end: { x: 0, y: 4 }, height: 2.7, thickness: 0.2 },
    { id: 'wall-4', start: { x: 0, y: 4 }, end: { x: 0, y: 0 }, height: 2.7, thickness: 0.2 },
  ],
  doors: [{ id: 'door-1', wallId: 'wall-1', offset: 2, width: 0.9, height: 2.1 }],
  windows: [
    { id: 'window-1', wallId: 'wall-1', offset: 7, width: 1.5, height: 1.2, sillHeight: 0.9 },
  ],
  furniture: [],
}