export const INTERVALS = [10, 25, 50] as const

export type SampleTrip = { origin: string; destination: string }

export const SAMPLE_TRIPS: SampleTrip[] = [
  { origin: 'Chicago, IL', destination: 'St. Louis, MO' },
  { origin: 'Denver, CO', destination: 'Salt Lake City, UT' },
  { origin: 'Minneapolis, MN', destination: 'Fargo, ND' },
]

export type FieldName = 'origin' | 'destination' | 'departure' | 'load' | 'interval'
export type FieldErrors = Record<FieldName, string | null>

export const NO_ERRORS: FieldErrors = { origin: null, destination: null, departure: null, load: null, interval: null }
export const MAX_DAYS_AHEAD = 14
const HOUR_MS = 3_600_000

type TripValues = {
  origin: { label: string } | null
  destination: { label: string } | null
  departure: string
  load: string
}

export function validateTrip(values: TripValues, now = new Date()): FieldErrors {
  const errors: FieldErrors = { ...NO_ERRORS }
  if (!values.origin?.label.trim()) errors.origin = 'Enter where the trip starts, or click the map.'
  if (!values.destination?.label.trim()) errors.destination = 'Enter where the trip ends, or click the map.'

  const departure = new Date(values.departure)
  if (!values.departure || Number.isNaN(departure.getTime())) {
    errors.departure = 'Choose a departure date and time.'
  } else if (departure.getTime() < now.getTime() - HOUR_MS) {
    errors.departure = 'Choose a departure time from now onwards.'
  } else if (departure.getTime() > now.getTime() + MAX_DAYS_AHEAD * 24 * HOUR_MS) {
    errors.departure = `Choose a departure within ${MAX_DAYS_AHEAD} days. The forecast ends after that.`
  }

  const load = Number(values.load)
  if (values.load.trim() === '' || !Number.isFinite(load)) errors.load = 'Enter the load in pounds, for example 40000.'
  else if (load < 0) errors.load = 'Enter a load of 0 lb or more.'
  return errors
}

export function firstError(errors: FieldErrors): FieldName | null {
  const order: FieldName[] = ['origin', 'destination', 'departure', 'load', 'interval']
  for (const field of order) if (errors[field]) return field
  return null
}

// show a backend 400 next to the field it is about
export function fieldForServerError(message: string, destinationText: string): FieldName | null {
  const lower = message.toLowerCase()
  if (lower.startsWith('no location found')) {
    const quoted = /'(.*)'/.exec(message)?.[1]
    return quoted !== undefined && quoted === destinationText ? 'destination' : 'origin'
  }
  if (lower.includes('same place')) return 'destination'
  if (lower.includes('valid latitude')) return 'origin'
  if (lower.includes('departure') || lower.includes('forecast')) return 'departure'
  if (lower.includes('load')) return 'load'
  if (lower.includes('interval')) return 'interval'
  return null
}

export function hoursBetween(from: string, to: string): number {
  return Math.round((new Date(to).getTime() - new Date(from).getTime()) / HOUR_MS)
}
