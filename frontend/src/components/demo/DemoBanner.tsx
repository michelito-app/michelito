import { MessageSquare, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { FeedbackDialog } from '@/components/demo/FeedbackDialog'
import { RestartDialog } from '@/components/demo/RestartDialog'
import { FOCUS } from '@/components/summary/styles'
import { useMode } from '@/lib/demo'
import { cn } from '@/lib/utils'

/** Cabecera fija de la demo: el aviso, el enlace al repo, «Empezar de nuevo» y «Opinar» (44 px).
 * Va en el flujo de la página (pegada arriba al desplazarse), así no tapa contenido en un
 * teléfono. */
export function DemoBanner() {
  const mode = useMode()
  const [open, setOpen] = useState<'opinar' | 'reiniciar' | null>(null)
  return (
    <header
      aria-label="Aviso de la demo"
      className="sticky top-0 z-20 flex w-full flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-secondary px-4 py-1 text-[13px] text-secondary-foreground"
    >
      <p className="min-w-0 flex-[1_1_220px] py-2">
        {mode.aviso ?? 'Demo con datos inventados · tus cambios se borran en 24 h'}
        {mode.repo && (
          <>
            {' · '}
            <a href={mode.repo} className="font-semibold underline" rel="noreferrer">
              Código abierto
            </a>
          </>
        )}
      </p>
      <button
        type="button"
        onClick={() => setOpen('reiniciar')}
        className={cn(
          'inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[10px] px-3 text-sm font-semibold hover:bg-muted/70',
          FOCUS,
        )}
      >
        <RotateCcw size={16} aria-hidden="true" />
        Empezar de nuevo
      </button>
      <button
        type="button"
        onClick={() => setOpen('opinar')}
        className={cn(
          'inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[10px] bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/85',
          FOCUS,
        )}
      >
        <MessageSquare size={16} aria-hidden="true" />
        Opinar
      </button>
      {open === 'opinar' && <FeedbackDialog onClose={() => setOpen(null)} />}
      {open === 'reiniciar' && <RestartDialog onClose={() => setOpen(null)} />}
    </header>
  )
}
