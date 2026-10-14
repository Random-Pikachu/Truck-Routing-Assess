import { MapPinOff } from 'lucide-react'
import { Component, type ReactNode } from 'react'

import type { Obstruction } from '../lib/camera'

type Props = { children: ReactNode; obstruction: Obstruction }
type State = { failed: boolean }

// MapLibre throws when WebGL 2 is unavailable; keep the planner usable without the map
export class MapErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div
        className="fixed inset-0 z-0 flex items-center justify-center bg-[oklch(0.95_0.004_256)] p-6"
        style={{ paddingInlineStart: this.props.obstruction.left + 24, paddingBottom: this.props.obstruction.bottom + 24 }}
        role="region"
        aria-label="Route map"
      >
        <div className="grid max-w-sm justify-items-center gap-2 text-center">
          <MapPinOff className="size-6 text-ink-faint" strokeWidth={1.5} aria-hidden="true" />
          <p className="text-sm font-semibold">The map can't be shown in this browser</p>
          <p className="text-[13px] leading-normal text-ink-muted text-pretty">
            Spotter needs WebGL 2 to draw the map. Turn on hardware acceleration in your browser settings, or open
            Spotter in another browser. Route results and checkpoints still work in the panel.
          </p>
        </div>
      </div>
    )
  }
}
