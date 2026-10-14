import { Eye, EyeOff, Pause, Play, RotateCcw } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { Heatmap } from '../lib/api'
import { formatDayClock } from '../lib/format'
import { RISK_LEVELS } from '../lib/risk'
import { cn, iconButton, quietButton } from '../lib/styles'
import { IconSwap } from './ui'

export type ForecastStatus = 'loading' | 'ready' | 'error'

type Props = {
  heatmap: Heatmap | null
  status: ForecastStatus
  hour: number
  visible: boolean
  departure: string
  onHour: (hour: number) => void
  onToggleVisible: () => void
  onRetry: () => void
}

const STEP_MS = 650

export function ForecastScrubber(props: Props) {
  const { heatmap, status, hour, visible, departure, onHour, onToggleVisible, onRetry } = props
  const [playing, setPlaying] = useState(false)
  const latestHour = useRef(hour)
  const lastHour = heatmap ? heatmap.hours - 1 : 48

  useLayoutEffect(() => {
    latestHour.current = hour
  })

  useEffect(() => {
    if (!playing) return
    const timer = window.setInterval(() => {
      const next = latestHour.current + 1
      if (next > lastHour) {
        setPlaying(false)
        return
      }
      onHour(next)
    }, STEP_MS)
    return () => window.clearInterval(timer)
  }, [playing, lastHour, onHour])

  const start = heatmap ? new Date(heatmap.startHour) : null
  const at = start ? new Date(start.getTime() + hour * 3_600_000) : null
  const departureHour = start ? Math.round((new Date(departure).getTime() - start.getTime()) / 3_600_000) : null
  const showDepartureTick = departureHour !== null && departureHour >= 0 && departureHour <= lastHour

  return (
    <section aria-labelledby="forecast-heading" className="grid gap-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className={cn(iconButton, 'disabled:opacity-40')}
          aria-label={playing ? 'Pause forecast playback' : 'Play the next 48 hours'}
          disabled={status !== 'ready'}
          onClick={() => {
            if (!playing && hour >= lastHour) onHour(0)
            setPlaying((value) => !value)
          }}
        >
          <IconSwap
            swapped={playing}
            icon={<Play className="size-4" strokeWidth={1.5} />}
            swappedIcon={<Pause className="size-4" strokeWidth={1.5} />}
          />
        </button>
        <div className="min-w-0 flex-1">
          <h2 id="forecast-heading" className="text-xs font-medium text-ink-muted">
            Forecast along your routes
          </h2>
          <p className="text-sm font-semibold tabular-nums">
            {at ? formatDayClock(at) : '—'}
            <span className="ms-1.5 font-normal text-ink-muted">{hour === 0 ? 'now' : `+${hour} h`}</span>
          </p>
        </div>
        <button
          type="button"
          className={iconButton}
          aria-label={visible ? 'Hide forecast layer' : 'Show forecast layer'}
          aria-pressed={visible}
          onClick={onToggleVisible}
        >
          <IconSwap
            swapped={!visible}
            icon={<Eye className="size-4" strokeWidth={1.5} />}
            swappedIcon={<EyeOff className="size-4" strokeWidth={1.5} />}
          />
        </button>
      </div>

      {status === 'loading' && (
        <div className="grid gap-1.5" role="status">
          <span className="skeleton h-2 w-full rounded-full" aria-hidden="true" />
          <p className="text-xs text-ink-muted">Loading the 48-hour forecast along your routes…</p>
        </div>
      )}

      {status === 'error' && (
        <div className="flex items-center justify-between gap-2" role="alert">
          <p className="text-xs text-ink-muted">The forecast layer couldn't load.</p>
          <button type="button" onClick={onRetry} className={cn(quietButton, 'h-8 px-2 text-xs')}>
            <RotateCcw className="size-3.5" strokeWidth={1.5} aria-hidden="true" />
            Try again
          </button>
        </div>
      )}

      {status === 'ready' && heatmap && (
        <div className="relative pt-4">
          {showDepartureTick && (
            <span
              className="absolute top-0 -translate-x-1/2 text-xs font-medium text-ink-muted"
              style={{ left: `calc(8px + (100% - 16px) * ${departureHour / lastHour})` }}
              aria-hidden="true"
            >
              Departs
            </span>
          )}
          <input
            type="range"
            min={0}
            max={lastHour}
            step={1}
            value={hour}
            onChange={(event) => {
              setPlaying(false)
              onHour(Number(event.target.value))
            }}
            aria-labelledby="forecast-heading"
            aria-valuetext={at ? `${formatDayClock(at)}, ${hour === 0 ? 'now' : `${hour} hours from now`}` : undefined}
            className="h-6 w-full cursor-pointer accent-ink"
          />
        </div>
      )}

      <ul className="flex flex-wrap gap-x-3 gap-y-1" aria-label="Risk colours">
        {RISK_LEVELS.map((level) => (
          <li key={level.name} className="flex items-center gap-1.5 text-xs text-ink-muted">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: level.color }} aria-hidden="true" />
            {level.label}
          </li>
        ))}
      </ul>
    </section>
  )
}
