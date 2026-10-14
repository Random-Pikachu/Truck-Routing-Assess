import * as maplibregl from 'maplibre-gl'
import type { GeoJSONSource, MapGeoJSONFeature } from 'maplibre-gl'
import type { Feature, FeatureCollection } from 'geojson'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { Checkpoint, Heatmap, LatLon, Route, TripPlan, Waypoint } from '../lib/api'
import { arrivalEasing, cameraDuration, framingPadding, type Obstruction } from '../lib/camera'
import { formatClock, formatDuration, formatInches } from '../lib/format'
import { cumulativeMiles, ownedStretches, pointAlong, slicePolyline, toLngLat } from '../lib/geometry'
import { riskColorExpression, riskLevelColorExpression, riskMeta } from '../lib/risk'

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const INK = '#1e2533'
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }

export type FramingTarget = 'route' | 'waypoints' | 'checkpoint'
export type FramingRequest = { target: FramingTarget; nonce: number }

type Props = {
  plan: TripPlan | null
  selectedRouteId: string | null
  origin: Waypoint | null
  destination: Waypoint | null
  heatmap: Heatmap | null
  heatmapHour: number | null
  openCheckpoint: number | null
  hoveredCheckpoint: number | null
  framing: FramingRequest | null
  obstruction: Obstruction
  reducedMotion: boolean
  onSelectRoute: (routeId: string) => void
  onOpenCheckpoint: (index: number | null) => void
  onMapClick: (lat: number, lon: number) => void
  onMoveWaypoint: (which: 'origin' | 'destination', lat: number, lon: number) => void
}

function selectedRoute(plan: TripPlan | null, routeId: string | null): Route | null {
  if (!plan) return null
  for (const route of plan.routes) if (route.routeId === routeId) return route
  return plan.routes[0] ?? null
}

function lineFeature(points: LatLon[], properties: Record<string, unknown>): Feature {
  const coordinates = []
  for (const point of points) coordinates.push(toLngLat(point))
  return { type: 'Feature', geometry: { type: 'LineString', coordinates }, properties }
}

function activeRiskFeatures(route: Route): FeatureCollection {
  const miles = cumulativeMiles(route.geometry)
  const checkpointMiles = []
  for (const checkpoint of route.checkpoints) checkpointMiles.push(checkpoint.mile)
  // geometry miles and checkpoint miles come from the same haversine sum, but scale defensively
  const scale = route.totalMiles > 0 ? miles[miles.length - 1] / route.totalMiles : 1
  const stretches = ownedStretches(checkpointMiles, route.totalMiles)

  const features = []
  for (let i = 0; i < route.checkpoints.length; i++) {
    const [from, to] = stretches[i]
    if (to <= from) continue
    const slice = slicePolyline(route.geometry, miles, from * scale, to * scale)
    features.push(lineFeature(slice, { risk: route.checkpoints[i].risk }))
  }
  return { type: 'FeatureCollection', features }
}

function checkpointFeatures(route: Route): FeatureCollection {
  const features: Feature[] = []
  for (let i = 0; i < route.checkpoints.length; i++) {
    const checkpoint = route.checkpoints[i]
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [checkpoint.lon, checkpoint.lat] },
      properties: { index: i, risk: checkpoint.risk },
    })
  }
  return { type: 'FeatureCollection', features }
}

function heatmapFeatures(heatmap: Heatmap): FeatureCollection {
  const features: Feature[] = []
  for (let p = 0; p < heatmap.points.length; p++) {
    const properties: Record<string, number> = {}
    for (let h = 0; h < heatmap.risk.length; h++) {
      const level = heatmap.risk[h][p]
      if (level !== null) properties[`r${h}`] = level
    }
    const [lat, lon] = heatmap.points[p]
    features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties })
  }
  return { type: 'FeatureCollection', features }
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

function popupHtml(checkpoint: Checkpoint, departure: string): string {
  const risk = riskMeta(checkpoint.risk)
  const weather = checkpoint.weather
  const gust = weather.gustMph === null ? '' : ` · gusts ${Math.round(weather.gustMph)}`
  const rows = [
    ['Wind', `${Math.round(weather.windMph)} mph${gust}`],
    ['Rain', `${formatInches(weather.rainInHr)}/hr`],
    ['Snow', `${formatInches(weather.snowInHr)}/hr`],
  ]
  let rowsHtml = ''
  for (const [label, value] of rows) {
    rowsHtml += `<div class="flex justify-between gap-6"><dt class="text-ink-muted">${label}</dt><dd class="tabular-nums">${escapeHtml(value)}</dd></div>`
  }
  return `
    <div class="min-w-48 text-[13px] leading-snug">
      <p class="pe-6 font-semibold tabular-nums">Mile ${Math.round(checkpoint.mile)} · ETA ${escapeHtml(formatClock(checkpoint.eta, departure))}</p>
      <p class="mt-1 flex items-center gap-1.5"><span class="size-2 rounded-full" style="background:${risk.color}"></span>${escapeHtml(risk.label)} risk</p>
      <dl class="mt-2 grid gap-0.5">${rowsHtml}</dl>
    </div>`
}

function originMarkerElement(): HTMLElement {
  const element = document.createElement('div')
  element.className = 'size-4 rounded-full border-[3px] border-ink bg-white shadow-[0_1px_3px_oklch(0_0_0/0.35)] cursor-grab'
  element.setAttribute('aria-hidden', 'true')
  return element
}

function destinationMarkerElement(): HTMLElement {
  const element = document.createElement('div')
  element.className = 'cursor-grab drop-shadow-[0_2px_3px_oklch(0_0_0/0.35)]'
  element.setAttribute('aria-hidden', 'true')
  element.innerHTML =
    '<svg width="26" height="32" viewBox="0 0 26 32"><path d="M13 31s11-10.4 11-18A11 11 0 0 0 2 13c0 7.6 11 18 11 18z" fill="#1e2533" stroke="white" stroke-width="2"/><circle cx="13" cy="13" r="4" fill="white"/></svg>'
  return element
}

function routePillElement(route: Route, active: boolean, onSelect: () => void): HTMLElement {
  const element = document.createElement('button')
  element.type = 'button'
  element.setAttribute('aria-label', `Show route ${route.routeId}, ${formatDuration(route.totalSeconds)}`)
  element.className = [
    'pressable flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums whitespace-nowrap',
    active
      ? 'bg-ink text-white shadow-[0_2px_8px_oklch(0_0_0/0.3)]'
      : 'bg-white text-ink shadow-[var(--shadow-border)] hover:shadow-[var(--shadow-border-hover)]',
  ].join(' ')
  element.innerHTML = `<span class="opacity-70">${escapeHtml(route.routeId)}</span><span>${escapeHtml(formatDuration(route.totalSeconds))}</span>`
  element.addEventListener('click', (event) => {
    event.stopPropagation()
    onSelect()
  })
  return element
}

export function MapCanvas(props: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const latest = useRef(props)
  const pillsRef = useRef<maplibregl.Marker[]>([])
  const waypointMarkers = useRef<{ origin: maplibregl.Marker | null; destination: maplibregl.Marker | null }>({
    origin: null,
    destination: null,
  })
  const popupRef = useRef<maplibregl.Popup | null>(null)

  useLayoutEffect(() => {
    latest.current = props
  })

  // ---- create the map once --------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: [-96, 38.5],
      zoom: 3.6,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    mapRef.current = map

    map.on('load', () => {
      const firstLabel = map.getStyle().layers.find((layer) => layer.type === 'symbol')?.id

      map.addSource('forecast', { type: 'geojson', data: EMPTY })
      map.addSource('routes', { type: 'geojson', data: EMPTY })
      map.addSource('active-risk', { type: 'geojson', data: EMPTY })
      map.addSource('checkpoints', { type: 'geojson', data: EMPTY })

      // forecast layer: soft circles sized to cover the 0.25 degree grid at every zoom
      map.addLayer(
        {
          id: 'forecast',
          type: 'circle',
          source: 'forecast',
          layout: { visibility: 'none' },
          paint: {
            'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 3, 1.6, 12, 820],
            'circle-color': '#000000',
            'circle-opacity': 0.32,
            'circle-blur': 0.85,
          },
        },
        firstLabel,
      )

      const round = { 'line-cap': 'round', 'line-join': 'round' } as const
      const alternative = ['==', ['get', 'active'], false] as maplibregl.FilterSpecification
      const active = ['==', ['get', 'active'], true] as maplibregl.FilterSpecification
      map.addLayer({ id: 'alt-casing', type: 'line', source: 'routes', filter: alternative, layout: round, paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 6, 10, 10] } }, firstLabel)
      map.addLayer({ id: 'alt-fill', type: 'line', source: 'routes', filter: alternative, layout: round, paint: { 'line-color': '#7d8aa0', 'line-opacity': 0.85, 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 3, 10, 6] } }, firstLabel)
      map.addLayer({ id: 'alt-hit', type: 'line', source: 'routes', filter: alternative, layout: round, paint: { 'line-color': '#000000', 'line-opacity': 0, 'line-width': 18 } }, firstLabel)
      map.addLayer({ id: 'active-casing', type: 'line', source: 'routes', filter: active, layout: round, paint: { 'line-color': INK, 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 8, 10, 13] } }, firstLabel)
      map.addLayer({ id: 'active-fill', type: 'line', source: 'active-risk', layout: round, paint: { 'line-color': riskColorExpression('risk'), 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 5, 10, 8] } }, firstLabel)

      map.addLayer({
        id: 'checkpoints',
        type: 'circle',
        source: 'checkpoints',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 4, 10, 6.5],
          'circle-color': riskColorExpression('risk'),
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
        },
      })
      map.addLayer({
        id: 'checkpoint-focus',
        type: 'circle',
        source: 'checkpoints',
        filter: ['==', ['get', 'index'], -1],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 8, 10, 11],
          'circle-color': 'rgba(0, 0, 0, 0)',
          'circle-stroke-color': INK,
          'circle-stroke-width': 2.5,
        },
      })

      const pointer = () => (map.getCanvas().style.cursor = 'pointer')
      const reset = () => (map.getCanvas().style.cursor = '')
      for (const layer of ['alt-hit', 'checkpoints']) {
        map.on('mouseenter', layer, pointer)
        map.on('mouseleave', layer, reset)
      }

      map.on('click', (event) => {
        const hits: MapGeoJSONFeature[] = map.queryRenderedFeatures(event.point, { layers: ['checkpoints', 'alt-hit'] })
        const checkpoint = hits.find((feature) => feature.layer.id === 'checkpoints')
        if (checkpoint) {
          latest.current.onOpenCheckpoint(Number(checkpoint.properties.index))
          return
        }
        const alternativeRoute = hits.find((feature) => feature.layer.id === 'alt-hit')
        if (alternativeRoute) {
          latest.current.onSelectRoute(String(alternativeRoute.properties.routeId))
          return
        }
        latest.current.onMapClick(event.lngLat.lat, event.lngLat.lng)
      })

      setReady(true)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  const { plan, selectedRouteId } = props
  const route = selectedRoute(plan, selectedRouteId)

  // ---- routes, risk-coloured active line, checkpoints, time pills ----------
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return

    const routeFeatures: Feature[] = []
    if (plan && route) {
      for (const candidate of plan.routes) {
        routeFeatures.push(lineFeature(candidate.geometry, { routeId: candidate.routeId, active: candidate.routeId === route.routeId }))
      }
    }
    ;(map.getSource('routes') as GeoJSONSource).setData({ type: 'FeatureCollection', features: routeFeatures })
    ;(map.getSource('active-risk') as GeoJSONSource).setData(route ? activeRiskFeatures(route) : EMPTY)
    ;(map.getSource('checkpoints') as GeoJSONSource).setData(route ? checkpointFeatures(route) : EMPTY)

    for (const pill of pillsRef.current) pill.remove()
    pillsRef.current = []
    if (plan && route) {
      const spots = [0.5, 0.36, 0.64]
      for (let i = 0; i < plan.routes.length; i++) {
        const candidate = plan.routes[i]
        const isActive = candidate.routeId === route.routeId
        const element = routePillElement(candidate, isActive, () => latest.current.onSelectRoute(candidate.routeId))
        const marker = new maplibregl.Marker({ element })
          .setLngLat(toLngLat(pointAlong(candidate.geometry, spots[i % spots.length])))
          .addTo(map)
        if (isActive) element.style.zIndex = '2'
        pillsRef.current.push(marker)
      }
    }
  }, [ready, plan, route])

  // ---- origin and destination markers (draggable) ---------------------------
  const { origin, destination } = props
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return

    const place = (which: 'origin' | 'destination', waypoint: Waypoint | null) => {
      const existing = waypointMarkers.current[which]
      if (!waypoint || waypoint.lat === undefined || waypoint.lon === undefined) {
        existing?.remove()
        waypointMarkers.current[which] = null
        return
      }
      if (existing) {
        existing.setLngLat([waypoint.lon, waypoint.lat])
        return
      }
      const element = which === 'origin' ? originMarkerElement() : destinationMarkerElement()
      const marker = new maplibregl.Marker({ element, draggable: true, anchor: which === 'origin' ? 'center' : 'bottom' })
        .setLngLat([waypoint.lon, waypoint.lat])
        .addTo(map)
      marker.on('dragend', () => {
        const { lat, lng } = marker.getLngLat()
        latest.current.onMoveWaypoint(which, lat, lng)
      })
      waypointMarkers.current[which] = marker
    }
    place('origin', origin)
    place('destination', destination)
  }, [ready, origin, destination])

  // ---- forecast layer -------------------------------------------------------
  const { heatmap, heatmapHour } = props
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    ;(map.getSource('forecast') as GeoJSONSource).setData(heatmap ? heatmapFeatures(heatmap) : EMPTY)
  }, [ready, heatmap])

  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    if (heatmapHour === null || !heatmap) {
      map.setLayoutProperty('forecast', 'visibility', 'none')
      return
    }
    const key = `r${heatmapHour}`
    map.setPaintProperty('forecast', 'circle-color', riskLevelColorExpression(key))
    map.setFilter('forecast', ['has', key])
    map.setLayoutProperty('forecast', 'visibility', 'visible')
  }, [ready, heatmap, heatmapHour])

  // ---- focused checkpoint ring and popup -----------------------------------
  const { openCheckpoint, hoveredCheckpoint } = props
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    const focus = hoveredCheckpoint ?? openCheckpoint ?? -1
    map.setFilter('checkpoint-focus', ['==', ['get', 'index'], focus])
  }, [ready, openCheckpoint, hoveredCheckpoint, route])

  useEffect(() => {
    const map = mapRef.current
    popupRef.current?.remove()
    popupRef.current = null
    if (!ready || !map || !plan || !route || openCheckpoint === null) return
    const checkpoint = route.checkpoints[openCheckpoint]
    if (!checkpoint) return

    const popup = new maplibregl.Popup({ offset: 14, maxWidth: '280px', focusAfterOpen: false })
      .setLngLat([checkpoint.lon, checkpoint.lat])
      .setHTML(popupHtml(checkpoint, plan.departure))
      .addTo(map)
    popup.on('close', () => {
      if (popupRef.current === popup) latest.current.onOpenCheckpoint(null)
    })
    popupRef.current = popup
  }, [ready, plan, route, openCheckpoint])

  // ---- camera: frame the subject inside what the dock leaves visible -------
  const { framing } = props
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map || !framing) return
    const { obstruction, reducedMotion, openCheckpoint: focusIndex } = latest.current
    const container = map.getContainer()
    const padding = framingPadding(container.clientWidth, container.clientHeight, obstruction)

    const points: LatLon[] = []
    if (framing.target === 'route' && route) {
      points.push(...route.geometry)
    } else if (framing.target === 'checkpoint' && route && focusIndex !== null && route.checkpoints[focusIndex]) {
      const checkpoint = route.checkpoints[focusIndex]
      map.easeTo({
        center: [checkpoint.lon, checkpoint.lat],
        zoom: Math.max(map.getZoom(), 7.5),
        padding,
        duration: cameraDuration(reducedMotion, 'near'),
        easing: arrivalEasing,
      })
      return
    } else {
      for (const waypoint of [latest.current.origin, latest.current.destination]) {
        if (waypoint && waypoint.lat !== undefined && waypoint.lon !== undefined) points.push([waypoint.lat, waypoint.lon])
      }
    }
    if (points.length === 0) return

    const bounds = new maplibregl.LngLatBounds()
    for (const point of points) bounds.extend(toLngLat(point))
    const current = map.getBounds()
    const travel = current.contains(bounds.getCenter()) ? 'near' : 'far'
    map.fitBounds(bounds, {
      padding,
      maxZoom: points.length === 1 ? 9 : 11,
      duration: cameraDuration(reducedMotion, travel),
      easing: arrivalEasing,
    })
  }, [ready, framing, route])

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-0"
      role="region"
      aria-label="Route map. Click the map to place the origin or destination."
    />
  )
}

