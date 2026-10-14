import { TriangleAlert } from 'lucide-react'

import type { Route, TripPlan } from '../lib/api'
import { formatDuration, formatMiles } from '../lib/format'
import { riskSummary, routeTradeoff, type Tone } from '../lib/routes'
import { cn } from '../lib/styles'
import { RiskStrip } from './RiskStrip'

const toneClass: Record<Tone, string> = {
  positive: 'bg-[oklch(0.94_0.05_158)] text-[oklch(0.38_0.09_158)]',
  neutral: 'bg-fill text-ink-muted',
  caution: 'bg-[oklch(0.95_0.05_60)] text-[oklch(0.45_0.12_50)]',
  danger: 'bg-[oklch(0.94_0.04_20)] text-[oklch(0.45_0.16_25)]',
}

type Props = {
  plan: TripPlan
  selectedRouteId: string | null
  onSelect: (routeId: string) => void
}

export function RouteList({ plan, selectedRouteId, onSelect }: Props) {
  let best: Route | null = null
  for (const route of plan.routes) if (route.routeId === plan.recommendedRouteId) best = route

  return (
    <section aria-labelledby="routes-heading" className="grid gap-2">
      <h2 id="routes-heading" className="sr-only">
        Route options
      </h2>
      {plan.recommendedRouteId ? (
        <p className="px-1 text-[13px] leading-snug text-ink text-pretty">{plan.reason}</p>
      ) : (
        <div className="flex gap-2 rounded-lg bg-[oklch(0.95_0.03_20)] px-3 py-2.5 text-[13px] leading-snug text-[oklch(0.4_0.14_25)]" role="note">
          <TriangleAlert className="mt-px size-4 shrink-0" strokeWidth={1.5} aria-hidden="true" />
          <p className="text-pretty">
            {plan.reason} Move the forecast slider to see when conditions improve, then try a later departure.
          </p>
        </div>
      )}

      <ul className="grid gap-1">
        {plan.routes.map((route) => {
          const selected = route.routeId === selectedRouteId
          const tradeoff = routeTradeoff(route, best)
          return (
            <li key={route.routeId}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(route.routeId)}
                className={cn(
                  'pressable relative grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 rounded-lg py-2.5 pe-3 ps-4 text-start',
                  selected ? 'bg-fill' : 'hover:bg-fill/60',
                )}
              >
                <span
                  className={cn(
                    'absolute inset-y-2.5 start-1.5 w-[3px] rounded-full bg-ink transition-[opacity] duration-150 ease-out',
                    selected ? 'opacity-100' : 'opacity-0',
                  )}
                  aria-hidden="true"
                />
                <span className="flex items-baseline gap-2">
                  <span className="text-[13px] font-medium text-ink-faint">{route.routeId}</span>
                  <span className="text-lg font-semibold leading-tight tabular-nums">{formatDuration(route.totalSeconds)}</span>
                </span>
                <span className={cn('whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium tabular-nums', toneClass[tradeoff.tone])}>
                  {tradeoff.label}
                </span>
                <span className="col-span-2 truncate text-[13px] text-ink-muted tabular-nums">
                  {formatMiles(route.totalMiles)} · {riskSummary(route)}
                </span>
                <span className="col-span-2 pt-1">
                  <RiskStrip route={route} />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
