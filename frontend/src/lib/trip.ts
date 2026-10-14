export const INTERVALS = [10, 25, 50] as const

export type SampleTrip = { origin: string; destination: string }

export const SAMPLE_TRIPS: SampleTrip[] = [
  { origin: 'Chicago, IL', destination: 'St. Louis, MO' },
  { origin: 'Denver, CO', destination: 'Salt Lake City, UT' },
  { origin: 'Minneapolis, MN', destination: 'Fargo, ND' },
]
