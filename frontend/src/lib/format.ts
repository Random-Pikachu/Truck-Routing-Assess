const clock = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })
const dayClock = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })

export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours === 0) return `${minutes}m`
  return `${hours}h ${String(minutes).padStart(2, '0')}m`
}

export function formatDelta(seconds: number): string {
  const sign = seconds < 0 ? '−' : '+'
  return `${sign}${formatDuration(Math.abs(seconds))}`
}

export function formatMiles(miles: number): string {
  const rounded = miles < 10 ? miles.toFixed(1) : Math.round(miles).toString()
  return `${rounded} mi`
}

export function formatClock(iso: string, reference?: string): string {
  const date = new Date(iso)
  if (reference && new Date(reference).toDateString() !== date.toDateString()) {
    return dayClock.format(date)
  }
  return clock.format(date)
}

export function formatDayClock(date: Date): string {
  return dayClock.format(date)
}

export function formatInches(inches: number): string {
  return inches === 0 ? '0 in' : `${inches.toFixed(2)} in`
}

// value for <input type="datetime-local"> in the browser's own timezone
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function nextFullHour(from = new Date()): Date {
  const date = new Date(from)
  date.setMinutes(0, 0, 0)
  date.setHours(date.getHours() + 1)
  return date
}
