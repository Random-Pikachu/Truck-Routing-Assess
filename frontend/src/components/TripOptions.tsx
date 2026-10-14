import { useId } from 'react'

import { cn } from '../lib/styles'
import { INTERVALS } from '../lib/trip'

export type TripOptionErrors = { departure: string | null; load: string | null; interval: string | null }

type Props = {
  departure: string
  departureMin: string
  departureMax: string
  load: string
  interval: number
  errors: TripOptionErrors
  onDeparture: (value: string) => void
  onLoad: (value: string) => void
  onInterval: (value: number) => void
}

const fieldLabel = 'mb-1 block text-xs font-medium text-ink-muted'
const fieldBox =
  'h-10 w-full rounded-lg bg-fill px-3 text-base text-ink tabular-nums outline-none transition-[box-shadow] duration-150 ease-out focus:bg-white focus:shadow-[0_0_0_2px_var(--color-accent)] sm:text-sm'
const invalid = 'shadow-[0_0_0_1.5px_var(--color-danger)]'

export function TripOptions(props: Props) {
  const { departure, departureMin, departureMax, load, interval, errors, onDeparture, onLoad, onInterval } = props
  const departureError = useId()
  const loadError = useId()
  const intervalLabel = useId()

  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-[1fr_7.5rem] gap-2">
        <div>
          <label htmlFor="departure" className={fieldLabel}>
            Departure
          </label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            min={departureMin}
            max={departureMax}
            onChange={(event) => onDeparture(event.target.value)}
            aria-invalid={errors.departure ? true : undefined}
            aria-describedby={errors.departure ? departureError : undefined}
            className={cn(fieldBox, errors.departure && invalid)}
          />
        </div>
        <div>
          <label htmlFor="load" className={fieldLabel}>
            Load
          </label>
          <div className="relative">
            <input
              id="load"
              type="number"
              inputMode="numeric"
              min={0}
              step={500}
              value={load}
              onChange={(event) => onLoad(event.target.value)}
              aria-invalid={errors.load ? true : undefined}
              aria-describedby={errors.load ? loadError : undefined}
              className={cn(fieldBox, 'pe-8', errors.load && invalid)}
            />
            <span className="pointer-events-none absolute inset-y-0 end-3 flex items-center text-[13px] text-ink-muted" aria-hidden="true">
              lb
            </span>
          </div>
        </div>
      </div>
      {(errors.departure || errors.load) && (
        <div className="-mt-2 grid gap-0.5 text-xs text-danger">
          {errors.departure && <p id={departureError}>{errors.departure}</p>}
          {errors.load && <p id={loadError}>{errors.load}</p>}
        </div>
      )}

      <div role="radiogroup" aria-labelledby={intervalLabel}>
        <span id={intervalLabel} className={fieldLabel}>
          Weather checkpoint every
        </span>
        <div className="grid grid-cols-3 gap-0.5 rounded-[10px] bg-fill p-0.5">
          {INTERVALS.map((miles) => (
            <label
              key={miles}
              className={cn(
                'pressable flex h-9 cursor-pointer items-center justify-center rounded-lg text-sm font-medium tabular-nums',
                'has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-accent',
                interval === miles ? 'bg-white text-ink shadow-[var(--shadow-border)]' : 'text-ink-muted hover:text-ink',
              )}
            >
              <input
                type="radio"
                name="interval"
                value={miles}
                checked={interval === miles}
                onChange={() => onInterval(miles)}
                className="sr-only"
              />
              {miles} mi
            </label>
          ))}
        </div>
        {errors.interval && <p className="mt-1 text-xs text-danger">{errors.interval}</p>}
      </div>
    </div>
  )
}
