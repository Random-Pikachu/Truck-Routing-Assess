import type { Route } from '../lib/api'
import { riskSegments } from '../lib/routes'

export function RiskStrip({ route }: { route: Route }) {
  return (
    <div className="flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-fill" aria-hidden="true">
      {riskSegments(route).map((segment, i) => (
        <span key={i} style={{ flexGrow: segment.miles, backgroundColor: segment.color }} className="h-full" />
      ))}
    </div>
  )
}
