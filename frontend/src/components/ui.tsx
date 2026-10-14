import type { ReactNode } from 'react'

import { cn } from '../lib/styles'

// both icons stay mounted and cross-fade: scale 0.25 -> 1, opacity, blur 4px -> 0
export function IconSwap({ swapped, icon, swappedIcon }: { swapped: boolean; icon: ReactNode; swappedIcon: ReactNode }) {
  const motion = 'flex items-center justify-center transition-[opacity,filter,scale] duration-300 ease-icon'
  const shown = 'scale-100 opacity-100 blur-[0px]'
  const hidden = 'scale-[0.25] opacity-0 blur-[4px]'
  return (
    <span className="relative inline-flex" aria-hidden="true">
      <span className={cn(motion, 'absolute inset-0', swapped ? shown : hidden)}>{swappedIcon}</span>
      <span className={cn(motion, swapped ? hidden : shown)}>{icon}</span>
    </span>
  )
}
