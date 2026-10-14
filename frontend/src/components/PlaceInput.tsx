import { LoaderCircle, LocateFixed, MapPin, X } from 'lucide-react'
import { useEffect, useId, useState, type KeyboardEvent, type Ref } from 'react'

import { reversePlace, searchPlaces, type Place, type Waypoint } from '../lib/api'
import { cn, iconButton } from '../lib/styles'

type Props = {
  id: string
  label: string
  placeholder: string
  value: Waypoint | null
  error: string | null
  allowCurrentLocation?: boolean
  inputRef?: Ref<HTMLInputElement>
  onChange: (waypoint: Waypoint | null) => void
  onFocus: () => void
}

type Option = { kind: 'current' } | { kind: 'place'; place: Place }

const MIN_QUERY = 2
const DEBOUNCE_MS = 220

function splitLabel(label: string): [string, string] {
  const comma = label.indexOf(',')
  if (comma === -1) return [label, '']
  return [label.slice(0, comma), label.slice(comma + 1).trim()]
}

export function PlaceInput(props: Props) {
  const { id, label, placeholder, value, error, allowCurrentLocation, inputRef, onChange, onFocus } = props
  const listId = useId()
  const errorId = useId()
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [results, setResults] = useState<{ query: string; places: Place[] }>({ query: '', places: [] })
  const [activeIndex, setActiveIndex] = useState(-1)
  const [locating, setLocating] = useState(false)
  const [locateError, setLocateError] = useState<string | null>(null)

  const text = value?.label ?? ''
  const isResolved = value?.lat !== undefined
  const query = isResolved ? '' : text.trim()
  const searchable = query.length >= MIN_QUERY
  // results belong to the query they were fetched for, so stale ones never show
  const suggestions = searchable && results.query === query ? results.places : []
  const searching = searchable && results.query !== query

  useEffect(() => {
    if (query.length < MIN_QUERY) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      searchPlaces(query, controller.signal)
        .then((places) => {
          setResults({ query, places })
          setActiveIndex(places.length > 0 ? 0 : -1)
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted) setResults({ query, places: [] })
          return error
        })
    }, DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [query])

  const options: Option[] = []
  if (allowCurrentLocation && text.length === 0) options.push({ kind: 'current' })
  for (const place of suggestions) options.push({ kind: 'place', place })
  const open = focused && !dismissed && (options.length > 0 || searching)
  const highlighted = activeIndex < options.length ? activeIndex : -1

  const choose = (option: Option) => {
    setDismissed(true)
    if (option.kind === 'place') {
      onChange(option.place)
      return
    }
    if (!('geolocation' in navigator)) {
      setLocateError("This browser can't share your location. Type a place instead.")
      return
    }
    setLocating(true)
    setLocateError(null)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        reversePlace(latitude, longitude)
          .then((place) => onChange(place))
          .catch(() => onChange({ label: `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`, lat: latitude, lon: longitude }))
          .finally(() => setLocating(false))
      },
      () => {
        setLocating(false)
        setLocateError('Location access is off for this site. Type a place or click the map instead.')
      },
      { timeout: 10_000 },
    )
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!open) {
        setDismissed(false)
        return
      }
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((index) => (index + step + options.length) % options.length)
    } else if (event.key === 'Enter' && open && highlighted >= 0) {
      event.preventDefault()
      choose(options[highlighted])
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      setDismissed(true)
    }
  }

  const describedBy = error || locateError ? errorId : undefined
  const activeOptionId = open && highlighted >= 0 ? `${listId}-${highlighted}` : undefined

  return (
    <div className="relative">
      <div
        className={cn(
          'flex h-10 items-center rounded-lg bg-fill pe-1 ps-3 transition-[box-shadow] duration-150 ease-out',
          'focus-within:bg-white focus-within:shadow-[0_0_0_2px_var(--color-accent)]',
          error && 'shadow-[0_0_0_1.5px_var(--color-danger)]',
        )}
      >
        <label htmlFor={id} className="w-9 shrink-0 text-[13px] text-ink-muted">
          {label}
        </label>
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={activeOptionId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          placeholder={placeholder}
          value={text}
          onChange={(event) => {
            setDismissed(false)
            setLocateError(null)
            onChange(event.target.value ? { label: event.target.value } : null)
          }}
          onFocus={() => {
            setFocused(true)
            setDismissed(false)
            onFocus()
          }}
          onBlur={() => setFocused(false)}
          onKeyDown={onKeyDown}
          className="h-full min-w-0 flex-1 truncate bg-transparent text-base text-ink outline-none placeholder:text-ink-faint sm:text-sm"
        />
        {locating && <LoaderCircle className="me-2 size-4 animate-spin text-ink-muted" aria-label="Finding your location" />}
        {text.length > 0 && !locating && (
          <button
            type="button"
            className={cn(iconButton, 'size-8')}
            aria-label={`Clear ${label.toLowerCase()}`}
            onClick={() => {
              onChange(null)
              const input = document.getElementById(id)
              input?.focus()
            }}
          >
            <X className="size-4" strokeWidth={1.5} />
          </button>
        )}
      </div>

      {(error || locateError) && (
        <p id={errorId} className="mt-1 ps-3 text-xs text-danger">
          {error ?? locateError}
        </p>
      )}

      <ul
        id={listId}
        role="listbox"
        aria-label={`${label} suggestions`}
        hidden={!open}
        className="absolute inset-x-0 top-11 z-30 max-h-72 overflow-y-auto rounded-xl bg-surface-solid p-1 shadow-dock"
      >
        {searching && (
          <li className="px-2.5 py-2 text-sm text-ink-muted" role="presentation">
            Searching places…
          </li>
        )}
        {options.map((option, index) => {
          const active = index === highlighted
          const optionId = `${listId}-${index}`
          const [primary, secondary] =
            option.kind === 'place' ? splitLabel(option.place.label) : ['Use current location', '']
          return (
            <li
              key={option.kind === 'place' ? `${option.place.lat},${option.place.lon},${index}` : 'current'}
              id={optionId}
              role="option"
              aria-selected={active}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(option)}
              className={cn(
                'flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm',
                active ? 'bg-fill text-ink' : 'text-ink',
              )}
            >
              {option.kind === 'current' ? (
                <LocateFixed className="size-4 shrink-0 text-accent" strokeWidth={1.5} aria-hidden="true" />
              ) : (
                <MapPin className="size-4 shrink-0 text-ink-faint" strokeWidth={1.5} aria-hidden="true" />
              )}
              <span className="min-w-0 truncate">
                <span className="font-medium">{primary}</span>
                {secondary && <span className="text-ink-muted"> · {secondary}</span>}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
