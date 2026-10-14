import type { LatLon } from './api'

const EARTH_RADIUS_MILES = 3958.8

export function haversineMiles(a: LatLon, b: LatLon): number {
  const toRad = Math.PI / 180
  const dLat = (b[0] - a[0]) * toRad
  const dLon = (b[1] - a[1]) * toRad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * toRad) * Math.cos(b[0] * toRad) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_MILES * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h))
}

export function cumulativeMiles(points: LatLon[]): number[] {
  const miles = [0]
  for (let i = 1; i < points.length; i++) {
    miles.push(miles[i - 1] + haversineMiles(points[i - 1], points[i]))
  }
  return miles
}

function pointAt(points: LatLon[], miles: number[], mile: number): LatLon {
  if (mile <= 0) return points[0]
  const last = points.length - 1
  if (mile >= miles[last]) return points[last]
  let hi = 1
  while (miles[hi] < mile) hi++
  const lo = hi - 1
  const span = miles[hi] - miles[lo]
  const t = span === 0 ? 0 : (mile - miles[lo]) / span
  return [points[lo][0] + t * (points[hi][0] - points[lo][0]), points[lo][1] + t * (points[hi][1] - points[lo][1])]
}

// part of a polyline between two road-mile marks, endpoints interpolated
export function slicePolyline(points: LatLon[], miles: number[], from: number, to: number): LatLon[] {
  const slice: LatLon[] = [pointAt(points, miles, from)]
  for (let i = 0; i < points.length; i++) {
    if (miles[i] > from && miles[i] < to) slice.push(points[i])
  }
  slice.push(pointAt(points, miles, to))
  return slice
}

export function pointAlong(points: LatLon[], fraction: number): LatLon {
  const miles = cumulativeMiles(points)
  return pointAt(points, miles, miles[miles.length - 1] * fraction)
}

// stretch of road each checkpoint stands for: halfway to its neighbours
export function ownedStretches(checkpointMiles: number[], totalMiles: number): [number, number][] {
  const stretches: [number, number][] = []
  const last = checkpointMiles.length - 1
  for (let i = 0; i <= last; i++) {
    const start = i === 0 ? 0 : (checkpointMiles[i - 1] + checkpointMiles[i]) / 2
    const end = i === last ? totalMiles : (checkpointMiles[i] + checkpointMiles[i + 1]) / 2
    stretches.push([start, end])
  }
  return stretches
}

export function toLngLat(point: LatLon): [number, number] {
  return [point[1], point[0]]
}
