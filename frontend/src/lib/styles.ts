export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}

export const primaryButton =
  'pressable inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-semibold text-white hover:bg-[oklch(0.32_0.02_256)] disabled:cursor-not-allowed disabled:opacity-60'

export const quietButton =
  'pressable inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium text-ink hover:bg-fill pointer-coarse:h-11'

export const iconButton =
  'pressable inline-flex size-9 shrink-0 items-center justify-center rounded-lg text-ink-muted hover:bg-fill hover:text-ink pointer-coarse:size-11'
