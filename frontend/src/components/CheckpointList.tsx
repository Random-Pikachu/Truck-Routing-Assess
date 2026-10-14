import type { Route } from '../lib/api'
import { formatClock, formatInches } from '../lib/format'
import { riskMeta } from '../lib/risk'
import { cn } from '../lib/styles'

type Props = {
  route: Route
  departure: string
  interval: number
  openCheckpoint: number | null
  onOpen: (index: number) => void
  onHover: (index: number | null) => void
}

function weatherLine(route: Route, index: number): string {
  const weather = route.checkpoints[index].weather
  const parts = [`Wind ${Math.round(weather.windMph)} mph`]
  if (weather.rainInHr > 0) parts.push(`rain ${formatInches(weather.rainInHr)}/hr`)
  if (weather.snowInHr > 0) parts.push(`snow ${formatInches(weather.snowInHr)}/hr`)
  if (parts.length === 1) parts.push('dry')
  return parts.join(' · ')
}

export function CheckpointList({ route, departure, interval, openCheckpoint, onOpen, onHover }: Props) {
  return (
    <section aria-labelledby="checkpoints-heading" className="grid gap-1">
      <div className="flex items-baseline justify-between px-1">
        <h2 id="checkpoints-heading" className="text-[13px] font-semibold">
          Route {route.routeId} checkpoints
        </h2>
        <p className="text-xs text-ink-muted tabular-nums">Every {interval} mi · forecast at ETA</p>
      </div>
      <ol className="grid" onMouseLeave={() => onHover(null)}>
        {route.checkpoints.map((checkpoint, index) => {
          const risk = riskMeta(checkpoint.risk)
          const open = openCheckpoint === index
          return (
            <li key={index}>
              <button
                type="button"
                aria-pressed={open}
                onClick={() => onOpen(index)}
                onMouseEnter={() => onHover(index)}
                onFocus={() => onHover(index)}
                onBlur={() => onHover(null)}
                className={cn(
                  'pressable grid w-full grid-cols-[10px_1fr_auto] items-center gap-x-2.5 rounded-lg px-2.5 py-2 text-start',
                  open ? 'bg-fill' : 'hover:bg-fill/60',
                )}
              >
                <span className="size-2.5 rounded-full" style={{ backgroundColor: risk.color }} aria-hidden="true" />
                <span className="min-w-0">
                  <span className="text-sm font-medium tabular-nums">{formatClock(checkpoint.eta, departure)}</span>
                  <span className="ms-2 text-xs text-ink-muted tabular-nums">mile {Math.round(checkpoint.mile)}</span>
                  <span className="block truncate text-xs text-ink-muted tabular-nums">{weatherLine(route, index)}</span>
                </span>
                <span className="text-xs font-medium">{risk.label}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
