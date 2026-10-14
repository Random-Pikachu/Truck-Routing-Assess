import type { ExpressionSpecification } from 'maplibre-gl'

import type { RiskName } from './api'

export type RiskMeta = { name: RiskName; label: string; color: string; level: number }

// hex rather than oklch: MapLibre paint properties need colors it can parse
export const RISK_LEVELS: RiskMeta[] = [
  { name: 'LOW', label: 'Low', color: '#2f9e6e', level: 0 },
  { name: 'MODERATE', label: 'Moderate', color: '#d9a90a', level: 1 },
  { name: 'HIGH', label: 'High', color: '#ef7a1a', level: 2 },
  { name: 'SEVERE', label: 'Severe', color: '#d6322c', level: 3 },
  { name: 'NO_TRAVEL', label: 'No travel', color: '#6b1f5c', level: 4 },
]

const BY_NAME: Record<string, RiskMeta> = {}
for (const meta of RISK_LEVELS) BY_NAME[meta.name] = meta

export function riskMeta(name: RiskName): RiskMeta {
  return BY_NAME[name]
}

export function riskColorExpression(property: string): ExpressionSpecification {
  const expression: unknown[] = ['match', ['get', property]]
  for (const meta of RISK_LEVELS) expression.push(meta.name, meta.color)
  expression.push('#94a3b8')
  return expression as ExpressionSpecification
}

// heatmap points store the risk as a level number (0 = LOW ... 4 = NO_TRAVEL)
export function riskLevelColorExpression(property: string): ExpressionSpecification {
  const expression: unknown[] = ['match', ['get', property]]
  for (const meta of RISK_LEVELS) expression.push(meta.level, meta.color)
  expression.push('rgba(0, 0, 0, 0)')
  return expression as ExpressionSpecification
}
