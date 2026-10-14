import { ArrowUpDown } from 'lucide-react'
import { useState, type Ref } from 'react'

import type { Waypoint } from '../lib/api'
import { cn, iconButton } from '../lib/styles'
import { PlaceInput } from './PlaceInput'

export type WaypointField = 'origin' | 'destination'

type Props = {
  origin: Waypoint | null
  destination: Waypoint | null
  originError: string | null
  destinationError: string | null
  originRef?: Ref<HTMLInputElement>
  destinationRef?: Ref<HTMLInputElement>
  onChange: (field: WaypointField, waypoint: Waypoint | null) => void
  onSwap: () => void
  onFocusField: (field: WaypointField) => void
}

export function WaypointSpine(props: Props) {
  const { origin, destination, originError, destinationError, originRef, destinationRef, onChange, onSwap, onFocusField } = props
  const [turns, setTurns] = useState(0)
  const canSwap = Boolean(origin || destination)

  return (
    <fieldset className="relative grid grid-cols-[16px_1fr_auto] gap-x-2">
      <legend className="sr-only">Origin and destination</legend>

      {/* hollow origin node -> dashed connector -> solid destination pin */}
      <div className="flex flex-col items-center pb-2 pt-[15px]" aria-hidden="true">
        <span className="size-2.5 shrink-0 rounded-full border-2 border-ink bg-white" />
        <span className="mt-1 w-0 flex-1 border-s-[1.5px] border-dashed border-ink-faint" />
      </div>
      <div className="pb-2">
        <PlaceInput
          id="origin"
          label="From"
          placeholder="Origin city or address"
          value={origin}
          error={originError}
          allowCurrentLocation
          inputRef={originRef}
          onChange={(waypoint) => onChange('origin', waypoint)}
          onFocus={() => onFocusField('origin')}
        />
      </div>

      <div className="col-start-3 row-span-2 row-start-1 flex items-center">
        <button
          type="button"
          className={cn(iconButton, 'disabled:opacity-40')}
          aria-label="Swap origin and destination"
          disabled={!canSwap}
          onClick={() => {
            setTurns((count) => count + 1)
            onSwap()
          }}
        >
          <ArrowUpDown
            className="size-4 transition-[rotate] duration-300 ease-icon"
            style={{ rotate: `${turns * 180}deg` }}
            strokeWidth={1.5}
          />
        </button>
      </div>

      <div className="col-start-1 row-start-2 flex flex-col items-center" aria-hidden="true">
        <span className="h-3 w-0 border-s-[1.5px] border-dashed border-ink-faint" />
        <svg className="mt-px shrink-0 text-ink" width="10" height="13" viewBox="0 0 10 13">
          <path d="M5 12.5S9.5 8.2 9.5 5A4.5 4.5 0 0 0 .5 5c0 3.2 4.5 7.5 4.5 7.5z" fill="currentColor" />
          <circle cx="5" cy="5" r="1.6" fill="white" />
        </svg>
      </div>
      <div className="col-start-2 row-start-2">
        <PlaceInput
          id="destination"
          label="To"
          placeholder="Destination city or address"
          value={destination}
          error={destinationError}
          inputRef={destinationRef}
          onChange={(waypoint) => onChange('destination', waypoint)}
          onFocus={() => onFocusField('destination')}
        />
      </div>
    </fieldset>
  )
}
