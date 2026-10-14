export type Obstruction = { left: number; bottom: number }

// cubic-bezier(0.22, 1, 0.36, 1): a gentle arrival with no overshoot
export function arrivalEasing(t: number): number {
  const x1 = 0.22
  const y1 = 1
  const x2 = 0.36
  const y2 = 1
  const sampleX = (u: number) => 3 * x1 * u * (1 - u) ** 2 + 3 * x2 * u ** 2 * (1 - u) + u ** 3
  const sampleY = (u: number) => 3 * y1 * u * (1 - u) ** 2 + 3 * y2 * u ** 2 * (1 - u) + u ** 3
  const slopeX = (u: number) => 3 * x1 * (1 - u) ** 2 + 6 * (x2 - x1) * u * (1 - u) + 3 * (1 - x2) * u ** 2

  let u = t
  for (let i = 0; i < 6; i++) {
    const slope = slopeX(u)
    if (Math.abs(slope) < 1e-6) break
    u -= (sampleX(u) - t) / slope
    u = Math.min(1, Math.max(0, u))
  }
  return sampleY(u)
}

// keep framed subjects inside an 8% safe area of whatever the floating UI leaves visible
export function framingPadding(width: number, height: number, obstruction: Obstruction) {
  const visibleWidth = Math.max(width - obstruction.left, 160)
  const visibleHeight = Math.max(height - obstruction.bottom, 160)
  const insetX = Math.max(32, visibleWidth * 0.08)
  const insetY = Math.max(32, visibleHeight * 0.08)
  return {
    top: insetY,
    bottom: obstruction.bottom + insetY,
    left: obstruction.left + insetX,
    right: insetX,
  }
}

export function cameraDuration(reducedMotion: boolean, travel: 'near' | 'far'): number {
  if (reducedMotion) return 0
  return travel === 'far' ? 900 : 600
}
