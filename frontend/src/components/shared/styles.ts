// Classes shared by the Shared screens: balance colors, rows, chips and list cards.
import { FOCUS } from '@/components/summary/styles'
import type { Tone } from '@/lib/ledger'
import { cn } from '@/lib/utils'

export const TONE_CLASS: Record<Tone, string> = {
  owed: 'text-down',
  owe: 'text-up',
  settled: 'text-muted-foreground',
}

/** A 44 px row-like button or link look. */
export const ROW_BUTTON = cn(
  'flex min-h-14 w-full min-w-0 items-center gap-3 px-3.5 py-2 text-left text-foreground no-underline hover:bg-muted/60',
  FOCUS,
  'focus-visible:ring-inset',
)

export const CHIP = cn(
  'inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold',
  FOCUS,
)
export const CHIP_ON = 'border-primary bg-secondary text-secondary-foreground'
export const CHIP_OFF = 'border-border bg-card text-ink-2 hover:bg-muted'

/** A list's card (rounded, bordered, rows divided). */
export const LIST_CARD =
  'flex flex-col overflow-hidden rounded-2xl border border-border bg-card [&>li]:border-b [&>li]:border-border [&>li:last-child]:border-b-0'
