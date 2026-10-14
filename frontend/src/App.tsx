import { LoaderCircle, Route as RouteIcon } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import { CheckpointList } from './components/CheckpointList'
import { Dock, type Snap } from './components/Dock'
import { ForecastScrubber, type ForecastStatus } from './components/ForecastScrubber'
import { MapCanvas, type FramingRequest, type FramingTarget } from './components/MapCanvas'
import { RouteList } from './components/RouteList'
import { EmptyState, ErrorState, LoadingState } from './components/States'
import { TripOptions } from './components/TripOptions'
import { IconSwap } from './components/ui'
import { WaypointSpine, type WaypointField } from './components/WaypointSpine'
import { useIsMobile, useReducedMotion } from './hooks/useMediaQuery'
import {
  ApiError,
  fetchHeatmap,
  planTrip,
  reversePlace,
  waypointQuery,
  type Heatmap,
  type PlanRequest,
  type TripPlan,
  type Waypoint,
} from './lib/api'
import type { Obstruction } from './lib/camera'
import { nextFullHour, toLocalInputValue } from './lib/format'
import { cn, primaryButton } from './lib/styles'
import {
  fieldForServerError,
  firstError,
  hoursBetween,
  MAX_DAYS_AHEAD,
  NO_ERRORS,
  validateTrip,
  type FieldErrors,
  type SampleTrip,
} from './lib/trip'

type Status = 'idle' | 'loading' | 'ready' | 'error'
type TripInputs = { origin: Waypoint | null; destination: Waypoint | null; departure: string; load: string; interval: number }

function buildRequest(inputs: TripInputs): PlanRequest {
  return {
    origin: inputs.origin ? waypointQuery(inputs.origin) : '',
    destination: inputs.destination ? waypointQuery(inputs.destination) : '',
    departure: inputs.departure ? new Date(inputs.departure).toISOString() : '',
    loadLb: Number(inputs.load),
    interval: inputs.interval,
  }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export default function App() {
  const isMobile = useIsMobile()
  const reducedMotion = useReducedMotion()

  const [origin, setOrigin] = useState<Waypoint | null>(null)
  const [destination, setDestination] = useState<Waypoint | null>(null)
  const [activeField, setActiveField] = useState<WaypointField>('origin')
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextFullHour()))
  const [load, setLoad] = useState('40000')
  const [intervalMiles, setIntervalMiles] = useState(25)
  const [errors, setErrors] = useState<FieldErrors>(NO_ERRORS)
  const [departureBounds] = useState(() => {
    const now = Date.now()
    return {
      min: toLocalInputValue(new Date(now - 60 * 60 * 1000)),
      max: toLocalInputValue(new Date(now + MAX_DAYS_AHEAD * 24 * 60 * 60 * 1000)),
    }
  })

  const [status, setStatus] = useState<Status>('idle')
  const [plan, setPlan] = useState<TripPlan | null>(null)
  const [planError, setPlanError] = useState<string | null>(null)
  const [submittedKey, setSubmittedKey] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [openCheckpoint, setOpenCheckpoint] = useState<number | null>(null)
  const [hoveredCheckpoint, setHoveredCheckpoint] = useState<number | null>(null)

  const [heatmap, setHeatmap] = useState<Heatmap | null>(null)
  const [heatmapStatus, setHeatmapStatus] = useState<ForecastStatus>('loading')
  const [heatmapHour, setHeatmapHour] = useState(0)
  const [heatmapVisible, setHeatmapVisible] = useState(true)
  const [heatmapRequest, setHeatmapRequest] = useState<PlanRequest | null>(null)

  const [framing, setFraming] = useState<FramingRequest | null>(null)
  const [dockObstruction, setDockObstruction] = useState<Obstruction>({ left: 0, bottom: 0 })
  const [scrubberHeight, setScrubberHeight] = useState(0)
  const [snap, setSnap] = useState<Snap>('half')

  const planAbort = useRef<AbortController | null>(null)
  const heatAbort = useRef<AbortController | null>(null)
  const framingNonce = useRef(0)
  const originRef = useRef<HTMLInputElement>(null)
  const destinationRef = useRef<HTMLInputElement>(null)
  const scrubberRef = useRef<HTMLDivElement>(null)

  const inputs: TripInputs = { origin, destination, departure, load, interval: intervalMiles }
  const inputKey = JSON.stringify(buildRequest(inputs))
  const stale = status === 'ready' && submittedKey !== null && inputKey !== submittedKey

  const frame = useCallback((target: FramingTarget) => {
    framingNonce.current += 1
    setFraming({ target, nonce: framingNonce.current })
  }, [])

  // ---- loading timer ---------------------------------------------------------
  useEffect(() => {
    if (status !== 'loading') return
    const timer = window.setInterval(() => setElapsed((seconds) => seconds + 1), 1000)
    return () => window.clearInterval(timer)
  }, [status])

  // ---- forecast layer ----------------------------------------------------------
  const loadHeatmap = useCallback((request: PlanRequest) => {
    heatAbort.current?.abort()
    const controller = new AbortController()
    heatAbort.current = controller
    setHeatmapRequest(request)
    setHeatmapStatus('loading')
    fetchHeatmap({ origin: request.origin, destination: request.destination, loadLb: request.loadLb }, controller.signal)
      .then((result) => {
        setHeatmap(result)
        const departureHour = hoursBetween(result.startHour, request.departure)
        setHeatmapHour(Math.min(result.hours - 1, Math.max(0, departureHour)))
        setHeatmapStatus('ready')
      })
      .catch((error: unknown) => {
        if (!isAbort(error)) setHeatmapStatus('error')
      })
  }, [])

  // ---- planning -----------------------------------------------------------------
  const runPlan = useCallback(
    (values: TripInputs) => {
      const validation = validateTrip(values)
      const invalid = firstError(validation)
      if (invalid) {
        setErrors(validation)
        if (isMobile) setSnap('full')
        if (invalid === 'origin') originRef.current?.focus()
        else if (invalid === 'destination') destinationRef.current?.focus()
        else document.getElementById(invalid)?.focus()
        return
      }

      const request = buildRequest(values)
      setErrors(NO_ERRORS)
      planAbort.current?.abort()
      heatAbort.current?.abort()
      const controller = new AbortController()
      planAbort.current = controller

      setStatus('loading')
      setPlan(null)
      setHeatmap(null)
      setPlanError(null)
      setElapsed(0)
      setOpenCheckpoint(null)
      setHoveredCheckpoint(null)
      if (isMobile) setSnap('half')

      planTrip(request, controller.signal)
        .then((result) => {
          setPlan(result)
          setSubmittedKey(JSON.stringify(request))
          setSelectedRouteId(result.recommendedRouteId ?? result.routes[0]?.routeId ?? null)
          setStatus('ready')
          frame('route')
          loadHeatmap(request)
        })
        .catch((error: unknown) => {
          if (isAbort(error)) return
          const message = error instanceof ApiError ? error.message : 'Unable to plan this trip. Try again.'
          const field = error instanceof ApiError && error.status === 400 ? fieldForServerError(message, request.destination) : null
          if (field) {
            setErrors({ ...NO_ERRORS, [field]: message })
            setStatus('idle')
            if (field === 'origin') originRef.current?.focus()
            else if (field === 'destination') destinationRef.current?.focus()
            else document.getElementById(field)?.focus()
            return
          }
          setPlanError(message)
          setStatus('error')
        })
    },
    [frame, isMobile, loadHeatmap],
  )

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    runPlan(inputs)
  }

  const onSample = (trip: SampleTrip) => {
    const sampleOrigin = { label: trip.origin }
    const sampleDestination = { label: trip.destination }
    setOrigin(sampleOrigin)
    setDestination(sampleDestination)
    runPlan({ ...inputs, origin: sampleOrigin, destination: sampleDestination })
  }

  // ---- waypoints from the map ----------------------------------------------------
  const setWaypoint = useCallback((field: WaypointField, update: (current: Waypoint | null) => Waypoint | null) => {
    if (field === 'origin') setOrigin(update)
    else setDestination(update)
  }, [])

  const placeWaypoint = useCallback(
    (field: WaypointField, lat: number, lon: number) => {
      setErrors((current) => ({ ...current, [field]: null }))
      setWaypoint(field, () => ({ label: `${lat.toFixed(5)}, ${lon.toFixed(5)}`, lat, lon }))
      reversePlace(lat, lon)
        .then((place) =>
          setWaypoint(field, (current) =>
            current && current.lat === lat && current.lon === lon ? { ...current, label: place.label } : current,
          ),
        )
        .catch(() => undefined)
    },
    [setWaypoint],
  )

  const onMapClick = useCallback(
    (lat: number, lon: number) => {
      const field: WaypointField = !origin ? 'origin' : !destination ? 'destination' : activeField
      placeWaypoint(field, lat, lon)
      if (field === 'origin') setActiveField('destination')
      if ((field === 'origin' && destination) || (field === 'destination' && origin)) frame('waypoints')
    },
    [origin, destination, activeField, placeWaypoint, frame],
  )

  const onSwap = () => {
    setOrigin(destination)
    setDestination(origin)
    setErrors((current) => ({ ...current, origin: current.destination, destination: current.origin }))
    if (origin && destination) frame('waypoints')
  }

  const onSelectRoute = useCallback(
    (routeId: string) => {
      setSelectedRouteId(routeId)
      setOpenCheckpoint(null)
      frame('route')
    },
    [frame],
  )

  // ---- keyboard: Escape closes the checkpoint popup ----------------------------------
  useEffect(() => {
    if (openCheckpoint === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenCheckpoint(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openCheckpoint])

  // ---- what the floating UI covers, for camera framing ---------------------------
  useLayoutEffect(() => {
    const element = scrubberRef.current
    if (!element) {
      setScrubberHeight(0)
      return
    }
    const observer = new ResizeObserver(() => setScrubberHeight(element.getBoundingClientRect().height))
    observer.observe(element)
    return () => observer.disconnect()
  }, [plan, isMobile])

  const obstruction = useMemo<Obstruction>(
    () => ({
      left: isMobile ? 0 : dockObstruction.left,
      bottom: isMobile ? dockObstruction.bottom : scrubberHeight > 0 ? scrubberHeight + 16 : 0,
    }),
    [isMobile, dockObstruction, scrubberHeight],
  )

  // markers for typed places use the coordinates the plan resolved them to
  const markerOrigin = origin?.lat !== undefined ? origin : plan && !stale ? plan.origin : null
  const markerDestination = destination?.lat !== undefined ? destination : plan && !stale ? plan.destination : null
  const selectedRoute = plan?.routes.find((route) => route.routeId === selectedRouteId) ?? null


  const scrubber = plan && (
    <ForecastScrubber
      heatmap={heatmap}
      status={heatmapStatus}
      hour={heatmapHour}
      visible={heatmapVisible}
      departure={plan.departure}
      onHour={setHeatmapHour}
      onToggleVisible={() => setHeatmapVisible((visible) => !visible)}
      onRetry={() => heatmapRequest && loadHeatmap(heatmapRequest)}
    />
  )

  const topPill =
    isMobile && origin && destination ? (
      <button
        type="button"
        onClick={() => setSnap('full')}
        className="dock-surface pressable pointer-events-auto flex h-9 max-w-full items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium"
      >
        <span className="truncate">{origin.label.split(',')[0]}</span>
        <span className="text-ink-faint" aria-hidden="true">
          →
        </span>
        <span className="truncate">{destination.label.split(',')[0]}</span>
        <span className="sr-only">. Open the trip planner</span>
      </button>
    ) : null

  return (
    <>
      <MapCanvas
        plan={plan}
        selectedRouteId={selectedRouteId}
        origin={markerOrigin}
        destination={markerDestination}
        heatmap={heatmap}
        heatmapHour={heatmapVisible && heatmapStatus === 'ready' ? heatmapHour : null}
        openCheckpoint={openCheckpoint}
        hoveredCheckpoint={hoveredCheckpoint}
        framing={framing}
        obstruction={obstruction}
        reducedMotion={reducedMotion}
        onSelectRoute={onSelectRoute}
        onOpenCheckpoint={setOpenCheckpoint}
        onMapClick={onMapClick}
        onMoveWaypoint={placeWaypoint}
      />

      <Dock isMobile={isMobile} snap={snap} topPill={topPill} onSnap={setSnap} onObstruction={setDockObstruction}>
        <div className="grid gap-4">
          <header className="flex items-baseline gap-2 px-1 pt-1">
            <h1 className="text-[15px] font-semibold tracking-tight">Spotter</h1>
            <p className="text-xs text-ink-muted">Weather-aware truck routing</p>
          </header>

          <form className="grid gap-3" onSubmit={onSubmit} noValidate aria-label="Trip details">
            <WaypointSpine
              origin={origin}
              destination={destination}
              originError={errors.origin}
              destinationError={errors.destination}
              originRef={originRef}
              destinationRef={destinationRef}
              onChange={(field, waypoint) => {
                setErrors((current) => ({ ...current, [field]: null }))
                setWaypoint(field, () => waypoint)
              }}
              onSwap={onSwap}
              onFocusField={(field) => {
                setActiveField(field)
                if (isMobile) setSnap('full')
              }}
            />
            <TripOptions
              departure={departure}
              departureMin={departureBounds.min}
              departureMax={departureBounds.max}
              load={load}
              interval={intervalMiles}
              errors={{ departure: errors.departure, load: errors.load, interval: errors.interval }}
              onDeparture={(value) => {
                setDeparture(value)
                setErrors((current) => ({ ...current, departure: null }))
              }}
              onLoad={(value) => {
                setLoad(value)
                setErrors((current) => ({ ...current, load: null }))
              }}
              onInterval={setIntervalMiles}
            />
            <button type="submit" className={cn(primaryButton, 'w-full')} disabled={status === 'loading'}>
              <IconSwap
                swapped={status === 'loading'}
                icon={<RouteIcon className="size-4" strokeWidth={2} />}
                swappedIcon={<LoaderCircle className="size-4 animate-spin" strokeWidth={2} />}
              />
              {status === 'loading' ? 'Finding routes…' : 'Find routes'}
            </button>
          </form>

          <div className="h-px bg-hairline" role="presentation" />

          <div aria-live="polite" className="grid gap-4">
            {status === 'idle' && <EmptyState onSample={onSample} />}
            {status === 'loading' && <LoadingState elapsedSeconds={elapsed} />}
            {status === 'error' && planError && <ErrorState message={planError} onRetry={() => runPlan(inputs)} />}
            {status === 'ready' && plan && (
              <>
                {stale && (
                  <p className="rounded-lg bg-fill px-3 py-2 text-[13px] text-ink-muted" role="status">
                    Trip details changed. Find routes again to update these results.
                  </p>
                )}
                <RouteList plan={plan} selectedRouteId={selectedRouteId} onSelect={onSelectRoute} />
                {isMobile && <div className="px-1">{scrubber}</div>}
                {selectedRoute && (
                  <CheckpointList
                    route={selectedRoute}
                    departure={plan.departure}
                    interval={plan.interval}
                    openCheckpoint={openCheckpoint}
                    onOpen={(index) => {
                      setOpenCheckpoint(index)
                      frame('checkpoint')
                    }}
                    onHover={setHoveredCheckpoint}
                  />
                )}
              </>
            )}
          </div>
        </div>
      </Dock>

      {!isMobile && plan && (
        <div
          ref={scrubberRef}
          className="dock-surface pointer-events-auto fixed bottom-4 start-[412px] z-10 w-[min(32rem,calc(100vw-412px-80px))] rounded-2xl p-3"
        >
          {scrubber}
        </div>
      )}
    </>
  )
}
