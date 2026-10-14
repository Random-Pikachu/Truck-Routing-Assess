export type RiskName = 'LOW' | 'MODERATE' | 'HIGH' | 'SEVERE' | 'NO_TRAVEL'
export type LatLon = [number, number]

export type Place = { label: string; lat: number; lon: number }

// a waypoint is a place once its coordinates are known (picked suggestion or map click)
export type Waypoint = { label: string; lat?: number; lon?: number }

export type Weather = {
  windMph: number
  gustMph: number | null
  rainInHr: number
  snowInHr: number
  forecastHour: string
}

export type Checkpoint = {
  mile: number
  lat: number
  lon: number
  secondsFromStart: number
  eta: string
  risk: RiskName
  weather: Weather
}

export type Route = {
  routeId: string
  rank: number
  recommended: boolean
  totalMiles: number
  totalSeconds: number
  summary: {
    milesPerRiskLevel: Record<RiskName, number>
    avgRisk: number
    drivable: boolean
  }
  geometry: LatLon[]
  checkpoints: Checkpoint[]
}

export type TripPlan = {
  origin: Place
  destination: Place
  departure: string
  loadLb: number
  interval: number
  recommendedRouteId: string | null
  reason: string
  routes: Route[]
}

export type Heatmap = {
  startHour: string
  hours: number
  levels: RiskName[]
  points: LatLon[]
  risk: (number | null)[][]
}

export type PlanRequest = {
  origin: string
  destination: string
  departure: string
  loadLb: number
  interval: number
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const API_BASE: string = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError("Can't reach the Spotter server. Check that it's running, then try again.", 0)
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const message = body && typeof body.error === 'string' ? body.error : `Request failed (${response.status})`
    throw new ApiError(message, response.status)
  }
  return body as T
}

function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

export async function searchPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  const data = await request<{ results: Place[] }>(`/api/geocode?q=${encodeURIComponent(query)}`, { signal })
  return data.results
}

export function reversePlace(lat: number, lon: number, signal?: AbortSignal): Promise<Place> {
  return request<Place>(`/api/reverse?lat=${lat}&lon=${lon}`, { signal })
}

export function planTrip(body: PlanRequest, signal?: AbortSignal): Promise<TripPlan> {
  return postJson<TripPlan>('/api/trips/plan', body, signal)
}

export function fetchHeatmap(
  body: Pick<PlanRequest, 'origin' | 'destination' | 'loadLb'>,
  signal?: AbortSignal,
): Promise<Heatmap> {
  return postJson<Heatmap>('/api/trips/heatmap', body, signal)
}

// coordinates when we have them, so the backend skips geocoding and uses the exact spot
export function waypointQuery(waypoint: Waypoint): string {
  if (waypoint.lat !== undefined && waypoint.lon !== undefined) {
    return `${waypoint.lat.toFixed(5)},${waypoint.lon.toFixed(5)}`
  }
  return waypoint.label.trim()
}
