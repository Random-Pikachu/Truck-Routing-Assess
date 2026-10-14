import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'

import type { Obstruction } from '../lib/camera'

export type Snap = 'peek' | 'half' | 'full'

type Props = {
  isMobile: boolean
  snap: Snap
  topPill: ReactNode
  children: ReactNode
  onSnap: (snap: Snap) => void
  onObstruction: (obstruction: Obstruction) => void
}

const ORDER: Snap[] = ['peek', 'half', 'full']

function snapHeights(viewportHeight: number): Record<Snap, number> {
  return {
    peek: 176,
    half: Math.round(viewportHeight * 0.52),
    full: Math.round(viewportHeight * 0.88),
  }
}

function useViewportHeight(): number {
  const [height, setHeight] = useState(() => window.innerHeight)
  useEffect(() => {
    const update = () => setHeight(window.innerHeight)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return height
}

export function Dock({ isMobile, snap, topPill, children, onSnap, onObstruction }: Props) {
  const asideRef = useRef<HTMLElement>(null)
  const viewportHeight = useViewportHeight()
  const heights = snapHeights(viewportHeight)
  const [drag, setDrag] = useState<{ startY: number; offset: number } | null>(null)
  const snapHeight = heights[snap]

  // desktop: the dock covers the left edge; mobile: the sheet covers the bottom
  useLayoutEffect(() => {
    if (isMobile) {
      onObstruction({ left: 0, bottom: snapHeight })
      return
    }
    const aside = asideRef.current
    if (!aside) return
    const report = () => onObstruction({ left: aside.getBoundingClientRect().right, bottom: 0 })
    report()
    const observer = new ResizeObserver(report)
    observer.observe(aside)
    return () => observer.disconnect()
  }, [isMobile, snapHeight, onObstruction])

  if (!isMobile) {
    return (
      <aside
        ref={asideRef}
        aria-label="Trip planner"
        className="pointer-events-none fixed bottom-4 start-4 top-4 z-10 flex w-[380px] flex-col"
      >
        <div className="dock-surface pointer-events-auto flex max-h-full flex-col overflow-hidden rounded-2xl">
          <div className="scroll-area overflow-y-auto overflow-x-hidden overscroll-contain p-2">{children}</div>
        </div>
      </aside>
    )
  }

  const visible = heights[snap] - (drag?.offset ?? 0)
  const clamped = Math.min(heights.full, Math.max(heights.peek - 40, visible))
  const nextSnap = ORDER[(ORDER.indexOf(snap) + 1) % ORDER.length]

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ startY: event.clientY, offset: 0 })
  }
  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (!drag) return
    setDrag({ ...drag, offset: event.clientY - drag.startY })
  }
  const onPointerUp = () => {
    if (!drag) return
    const moved = Math.abs(drag.offset) > 6
    setDrag(null)
    if (!moved) {
      onSnap(nextSnap)
      return
    }
    let nearest: Snap = 'peek'
    for (const candidate of ORDER) {
      if (Math.abs(heights[candidate] - clamped) < Math.abs(heights[nearest] - clamped)) nearest = candidate
    }
    onSnap(nearest)
  }

  return (
    <>
      {topPill && <div className="pointer-events-none fixed inset-x-3 top-3 z-10 flex justify-center">{topPill}</div>}
      <section
        aria-label="Trip planner"
        className="dock-surface pointer-events-auto fixed inset-x-0 bottom-0 z-10 flex flex-col rounded-t-2xl"
        style={{
          height: heights.full,
          transform: `translateY(${heights.full - clamped}px)`,
          transition: drag ? 'none' : 'transform 320ms var(--ease-arrival)',
        }}
      >
        <button
          type="button"
          aria-label={snap === 'full' ? 'Collapse planner' : 'Expand planner'}
          aria-expanded={snap !== 'peek'}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => setDrag(null)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onSnap(nextSnap)
            }
          }}
          className="flex h-7 w-full shrink-0 touch-none cursor-grab items-center justify-center"
        >
          <span className="h-1 w-9 rounded-full bg-ink/20" aria-hidden="true" />
        </button>
        <div className="scroll-area min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain px-2 pb-[max(12px,env(safe-area-inset-bottom))]">
          {children}
        </div>
      </section>
    </>
  )
}
