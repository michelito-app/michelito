// Clases compartidas por las piezas del Resumen.
import type { Tone } from '@/lib/summary'

export const PANEL = 'rounded-2xl border border-border bg-card'
export const PANEL_TITLE = 'text-[17px] font-[650] tracking-tight'
export const ROW_DIVIDER = 'border-b border-[#F2F2EE] last:border-b-0'
export const FOCUS =
  'outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-offset-0'

/** Los widgets cortos del pie del Resumen: mismo alto en su fila. */
export const WIDGET = `${PANEL} flex h-full min-w-0 flex-col gap-3 px-5 py-4`
/** Enlace o botón "Ver todos" en la cabecera de un widget (44 px de alto). */
export const WIDGET_ACTION = `-mr-2 inline-flex min-h-11 shrink-0 items-center gap-1 rounded-md px-2 text-[13px] font-semibold text-primary no-underline hover:bg-muted/60 ${FOCUS}`

export const TONE_TEXT: Record<Tone, string> = {
  up: 'text-up',
  down: 'text-down',
  same: 'text-muted-foreground',
  none: 'text-muted-foreground',
}
