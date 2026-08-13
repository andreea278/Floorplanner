import type { FloorPlan } from '@/types/floorPlan'

const API_BASE_URL = 'http://127.0.0.1:8000'

export class FloorPlanApiError extends Error {}

export async function detectFloorPlan(file: File): Promise<FloorPlan> {
  const formData = new FormData()
  formData.append('file', file)

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/floorplan/detect`, {
      method: 'POST',
      body: formData,
    })
  } catch (err) {
    throw new FloorPlanApiError(
      'Could not reach the backend. Is it running on port 8000?',
    )
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail ?? `Request failed with status ${response.status}`
    throw new FloorPlanApiError(detail)
  }

  return (await response.json()) as FloorPlan
}