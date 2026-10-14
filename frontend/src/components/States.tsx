import { ArrowRight, RotateCcw, TriangleAlert } from 'lucide-react'

import { cn, quietButton } from '../lib/styles'
import { SAMPLE_TRIPS, type SampleTrip } from '../lib/trip'

export function EmptyState({ onSample }: { onSample: (trip: SampleTrip) => void }) {
  return (
    <section className="grid gap-3 px-1" aria-labelledby="empty-heading">
      <div className="grid gap-1">
        <h2 id="empty-heading" className="text-sm font-semibold">
          Plan a weather-checked route
        </h2>
        <p className="text-[13px] leading-normal text-ink-muted text-pretty">
          Enter an origin and destination, or click the map to place them. Each route is scored with the forecast for
          the hour your truck reaches every checkpoint.
        </p>
      </div>
      <div className="grid gap-1">
        <p className="text-xs font-medium text-ink-muted">Try a sample trip</p>
        <ul className="-mx-1 grid">
          {SAMPLE_TRIPS.map((trip) => (
            <li key={trip.origin}>
              <button
                type="button"
                onClick={() => onSample(trip)}
                className="pressable flex h-9 w-full items-center justify-between gap-2 rounded-lg px-2 text-start text-sm text-ink hover:bg-fill"
              >
                <span className="truncate">
                  {trip.origin} <span className="text-ink-faint">→</span> {trip.destination}
                </span>
                <ArrowRight className="size-4 shrink-0 text-ink-faint" strokeWidth={1.5} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

export function LoadingState({ elapsedSeconds }: { elapsedSeconds: number }) {
  return (
    <section className="grid gap-2" aria-busy="true" aria-labelledby="loading-heading">
      <div className="px-1" role="status">
        <h2 id="loading-heading" className="text-[13px] font-medium">
          Finding routes and checking forecasts <span className="text-ink-muted tabular-nums">· {elapsedSeconds} s</span>
        </h2>
        <p className="text-xs text-ink-muted">A new trip can take up to 30 seconds. Repeat trips load instantly.</p>
      </div>
      <ul className="grid gap-1" aria-hidden="true">
        {[0, 1, 2].map((row) => (
          <li key={row} className="grid gap-2 rounded-lg py-3 pe-3 ps-4">
            <div className="flex justify-between">
              <span className="skeleton h-5 w-24 rounded-md" />
              <span className="skeleton h-5 w-20 rounded-full" />
            </div>
            <span className="skeleton h-3.5 w-40 rounded-md" />
            <span className="skeleton h-1.5 w-full rounded-full" />
          </li>
        ))}
      </ul>
    </section>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="grid gap-2 rounded-lg bg-[oklch(0.96_0.025_20)] p-3" role="alert">
      <div className="flex gap-2 text-[13px] leading-snug text-[oklch(0.4_0.14_25)]">
        <TriangleAlert className="mt-px size-4 shrink-0" strokeWidth={1.5} aria-hidden="true" />
        <p className="text-pretty">{message}</p>
      </div>
      <button type="button" onClick={onRetry} className={cn(quietButton, 'justify-self-start bg-white shadow-[var(--shadow-border)]')}>
        <RotateCcw className="size-4" strokeWidth={1.5} aria-hidden="true" />
        Try again
      </button>
    </section>
  )
}
