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

export type Tone = 'positive' | 'neutral' | 'caution' | 'danger'
export type Tradeoff = { label: string; tone: Tone }

function milesAt(route: Route, level: keyof Route['summary']['milesPerRiskLevel']): number {
  return route.summary.milesPerRiskLevel[level] ?? 0
}

// the one difference that explains why a route ranks where it does
export function routeTradeoff(route: Route, best: Route | null): Tradeoff {
  if (!route.summary.drivable) return { label: 'Not drivable', tone: 'danger' }
  if (route.recommended || !best) return { label: 'Recommended', tone: 'positive' }

  const severe = milesAt(route, 'SEVERE') - milesAt(best, 'SEVERE')
  if (severe > 1) return { label: `+${Math.round(severe)} mi severe`, tone: 'danger' }
  const high = milesAt(route, 'HIGH') - milesAt(best, 'HIGH')
  if (high > 1) return { label: `+${Math.round(high)} mi high risk`, tone: 'caution' }
  if (route.summary.avgRisk - best.summary.avgRisk > 0.05) return { label: 'More exposure', tone: 'caution' }

  const seconds = route.totalSeconds - best.totalSeconds
  if (seconds >= 60) {
    const minutes = Math.round(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const label = hours > 0 ? `+${hours}h ${String(minutes % 60).padStart(2, '0')}m` : `+${minutes} min`
    return { label, tone: 'neutral' }
  }
  return { label: 'Same time', tone: 'neutral' }
}

export function riskSummary(route: Route): string {
  if (!route.summary.drivable) {
    const blocked = route.checkpoints.find((checkpoint) => checkpoint.risk === 'NO_TRAVEL')
    return blocked ? `No travel near mile ${Math.round(blocked.mile)}` : 'No travel on part of the route'
  }
  const parts = []
  const severe = Math.round(milesAt(route, 'SEVERE'))
  const high = Math.round(milesAt(route, 'HIGH'))
  const moderate = Math.round(milesAt(route, 'MODERATE'))
  if (severe > 0) parts.push(`${severe} mi severe`)
  if (high > 0) parts.push(`${high} mi high`)
  if (parts.length > 0) return parts.join(' · ')
  if (moderate > 0) return `${moderate} mi moderate, rest low`
  return 'Low risk the whole way'
}
