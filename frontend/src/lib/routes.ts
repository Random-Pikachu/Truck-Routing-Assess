import type { Route } from './api'
import { ownedStretches } from './geometry'
import { riskMeta } from './risk'

export type RiskSegment = { color: string; miles: number }

// the route's risk in road order, so a strip reads like the line on the map
export function riskSegments(route: Route): RiskSegment[] {
  const miles = []
  for (const checkpoint of route.checkpoints) miles.push(checkpoint.mile)
  const stretches = ownedStretches(miles, route.totalMiles)

  const segments: RiskSegment[] = []
  for (let i = 0; i < route.checkpoints.length; i++) {
    const color = riskMeta(route.checkpoints[i].risk).color
    const length = stretches[i][1] - stretches[i][0]
    const previous = segments[segments.length - 1]
    if (previous && previous.color === color) previous.miles += length
    else segments.push({ color, miles: length })
  }
  return segments
}
